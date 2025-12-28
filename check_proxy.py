#!/usr/bin/env python3
"""
代理检测脚本 (Python版本)
从指定文件读取代理IP:端口，使用在线服务检测代理可用性
支持并发检测并按响应时间排序保存成功结果
增加多次检测取平均值功能，整合下载速度和延迟数据
"""

import os
import sys
import re
import json
import time
import threading
import statistics
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# 检查是否安装了requests库
try:
    import requests
except ImportError:
    print("错误: requests 库未安装")
    print("请安装 requests: pip install requests")
    sys.exit(1)

# 全局锁，用于保护文件写入操作
file_lock = threading.Lock()

def check_termux():
    """检查是否在Termux环境中"""
    return os.path.exists("/data/data/com.termux/files/usr")

def parse_input_param(param):
    """解析输入参数，确定文件路径"""
    input_param = param
    
    # 如果输入的是完整路径且文件存在
    if os.path.isfile(input_param):
        return input_param
    
    # 输入格式为 as123
    if re.match(r'^as[0-9]+$', input_param):
        num_part = input_param[2:]  # 去掉'as'
        return f"{input_param}/iptest_as{num_part}.txt"
    
    # 输入格式为 123
    if re.match(r'^[0-9]+$', input_param):
        return f"as{input_param}/iptest_as{input_param}.txt"
    
    # 输入格式为 iptest_as123.txt
    if re.match(r'^iptest_as[0-9]+\.txt$', input_param):
        # 先尝试在当前目录查找
        if os.path.isfile(input_param):
            return input_param
        else:
            # 尝试从文件名中提取数字
            match = re.match(r'iptest_as([0-9]+)\.txt', input_param)
            if match:
                num_part = match.group(1)
                return f"as{num_part}/{input_param}"
            else:
                return input_param
    
    # 其他格式，尝试作为路径处理
    return input_param

def find_proxy_files():
    """查找可能的代理测试文件"""
    print("正在查找代理测试文件...")
    
    # 查找当前目录下的iptest_as*.txt文件
    print("当前目录下的文件:")
    for file in Path('.').glob('iptest_as*.txt'):
        if file.is_file():
            print(f"  - {file}")
    
    print("\nasxxx文件夹中的文件:")
    for dir_path in Path('.').glob('as*/'):
        if dir_path.is_dir():
            for file in dir_path.glob('iptest_as*.txt'):
                if file.is_file():
                    print(f"  - {file}")

def check_proxy_single(proxy, timeout=15):
    """单次检测单个代理"""
    url = f"https://check.proxyip.vlato.site/check?proxyip={proxy}"
    
    # Termux环境使用更长超时
    if check_termux():
        timeout = 30
    
    try:
        # 发送请求
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        
        # 解析JSON响应
        data = response.json()
        success = data.get('success')
        response_time = data.get('responseTime')
        error_msg = data.get('message') or data.get('error')
        
        return {
            'success': success,
            'response_time': response_time,
            'error_msg': error_msg,
            'raw_response': data
        }
        
    except requests.exceptions.Timeout:
        return {'timeout': True, 'error': '请求超时'}
    except requests.exceptions.ConnectionError:
        return {'error': '连接失败'}
    except requests.exceptions.RequestException as e:
        return {'error': f'请求失败: {str(e)}'}
    except json.JSONDecodeError:
        return {'error': '响应格式错误，非JSON格式'}
    except Exception as e:
        return {'error': f'未知错误: {str(e)}'}

def check_proxy_multiple(proxy, test_times=3):
    """多次检测单个代理，返回平均响应时间"""
    response_times = []
    
    for i in range(test_times):
        result = check_proxy_single(proxy)
        
        # 如果任何一次检测失败，返回失败
        if 'timeout' in result:
            return {'timeout': True, 'error': f'第{i+1}次检测请求超时'}
        elif 'error' in result:
            return {'error': f'第{i+1}次检测{result["error"]}'}
        elif result.get('success') not in [True, 'true', 'True']:
            error_msg = result.get('error_msg', '检测失败')
            return {'error': f'第{i+1}次检测{error_msg}'}
        
        # 提取响应时间
        response_time = result.get('response_time')
        if response_time:
            # 提取数字部分
            try:
                rt_num = int(re.sub(r'[^0-9]', '', str(response_time)))
                response_times.append(rt_num)
            except:
                # 如果无法解析响应时间，使用默认值
                response_times.append(1000)
        
        # 在多次检测之间添加短暂延迟
        if i < test_times - 1:
            time.sleep(0.5)
    
    # 计算平均响应时间
    if response_times:
        avg_response_time = int(statistics.mean(response_times))
        return {
            'success': True,
            'response_times': response_times,
            'avg_response_time': avg_response_time,
            'min_response_time': min(response_times),
            'max_response_time': max(response_times)
        }
    else:
        return {'error': '无法获取响应时间'}

def read_download_speeds_from_csv(csv_file_path):
    """从CSV文件读取下载速度数据（直接使用CSV中的原始值）"""
    download_speeds = {}
    
    if not os.path.exists(csv_file_path):
        print(f"警告: 未找到CSV文件 {csv_file_path}")
        return download_speeds
    
    try:
        import csv
        
        print(f"正在读取CSV文件: {csv_file_path}")
        
        with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
            # 检测CSV文件的delimiter
            sample = csvfile.read(1024)
            csvfile.seek(0)
            
            # 尝试判断分隔符
            if ',' in sample:
                delimiter = ','
            elif ';' in sample:
                delimiter = ';'
            elif '\t' in sample:
                delimiter = '\t'
            else:
                # 默认使用逗号
                delimiter = ','
            
            print(f"使用分隔符: '{delimiter}'")
            
            reader = csv.reader(csvfile, delimiter=delimiter)
            
            # 读取表头
            headers = next(reader, None)
            if not headers:
                print(f"CSV文件为空: {csv_file_path}")
                return download_speeds
            
            print(f"CSV表头: {headers}")
            
            # 查找列索引 - 修正：只需要查找IP和端口列，确保正确的列
            ip_col_idx = -1
            port_col_idx = -1
            download_col_idx = -1
            
            for i, header in enumerate(headers):
                header_str = str(header).strip().lower()
                
                # 只匹配确切的IP地址列名，避免匹配到"源IP位置"
                if header_str in ['ip地址', 'ip address', 'ip']:
                    ip_col_idx = i
                    print(f"找到IP地址列: 索引 {i}, 名称 '{headers[i]}'")
                
                # 端口列
                if header_str in ['端口', '端口号', 'port']:
                    port_col_idx = i
                    print(f"找到端口列: 索引 {i}, 名称 '{headers[i]}'")
                
                # 下载速度列
                if '下载速度' in header_str or header_str in ['download', 'speed']:
                    download_col_idx = i
                    print(f"找到下载速度列: 索引 {i}, 名称 '{headers[i]}'")
            
            # 如果没找到明确的IP列，使用第一列（根据CSV格式，第一列通常是IP地址）
            if ip_col_idx == -1:
                ip_col_idx = 0
                print(f"使用默认IP列: 索引 0, 名称 '{headers[0]}'")
            
            # 如果没找到端口列，使用第二列
            if port_col_idx == -1:
                port_col_idx = 1
                print(f"使用默认端口列: 索引 1, 名称 '{headers[1]}'")
            
            if download_col_idx == -1:
                print(f"CSV文件中未找到下载速度列: {csv_file_path}")
                # 尝试最后一个列
                download_col_idx = len(headers) - 1
                print(f"尝试使用最后一列作为下载速度: 索引 {download_col_idx}, 名称 '{headers[download_col_idx]}'")
            
            # 验证列索引
            if ip_col_idx == -1 or port_col_idx == -1 or download_col_idx == -1:
                print(f"无法确定必要的列: IP={ip_col_idx}, 端口={port_col_idx}, 下载速度={download_col_idx}")
                return download_speeds
            
            print(f"使用列索引: IP[{ip_col_idx}], 端口[{port_col_idx}], 下载速度[{download_col_idx}]")
            
            # 读取数据行
            row_count = 0
            speed_count = 0
            for row in reader:
                row_count += 1
                
                # 确保行有足够的列
                if len(row) <= max(ip_col_idx, port_col_idx, download_col_idx):
                    print(f"第{row_count}行列数不足，跳过")
                    continue
                
                ip = row[ip_col_idx].strip()
                port = row[port_col_idx].strip()
                download_speed_str = row[download_col_idx].strip()
                
                # 检查IP地址格式是否正确
                if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
                    print(f"第{row_count}行IP地址格式不正确: {ip}")
                    continue
                
                if ip and port and download_speed_str:
                    key = f"{ip}:{port}"
                    download_speeds[key] = download_speed_str
                    speed_count += 1
                    
                    # 显示前几个数据用于验证
                    if speed_count <= 3:
                        print(f"  示例数据: {key} -> {download_speed_str}")
                else:
                    print(f"第{row_count}行数据不完整: IP={ip}, 端口={port}, 下载速度={download_speed_str}")
        
        print(f"从CSV文件读取了 {row_count} 行数据，成功提取 {speed_count} 个代理的下载速度数据")
        
        # 显示一些统计信息
        if speed_count > 0:
            print(f"下载速度数据示例:")
            count = 0
            for key, speed in list(download_speeds.items())[:5]:
                print(f"  {key}: {speed}")
                count += 1
            if len(download_speeds) > 5:
                print(f"  ... 还有 {len(download_speeds) - 5} 个代理的下载速度数据")
        
    except ImportError:
        print("错误: 需要csv模块，但在Python标准库中应该可用")
        return {}
    except Exception as e:
        print(f"读取CSV文件时出错: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return download_speeds

def parse_download_speed_for_display(speed_str):
    """解析下载速度字符串用于显示和评分计算"""
    if not speed_str:
        return 0, "0"
    
    try:
        # 提取数字部分
        match = re.search(r'([\d.]+)', speed_str)
        if match:
            speed_num = float(match.group(1))
            
            # 确定单位
            if 'kb/s' in speed_str.lower() or 'kbps' in speed_str.lower():
                # kB/s 转换为数字评分值（假设1 kB/s = 0.1评分值）
                return speed_num * 0.1, speed_str
            elif 'mb/s' in speed_str.lower() or 'mbps' in speed_str.lower():
                # MB/s 转换为数字评分值（假设1 MB/s = 100评分值）
                return speed_num * 100, speed_str
            else:
                # 默认假设是kB/s
                return speed_num * 0.1, speed_str
        else:
            return 0, "0"
    except:
        return 0, "0"

def read_download_speeds(iptest_file):
    """读取下载速度数据（从CSV文件）"""
    # 根据TXT文件路径找到对应的CSV文件路径
    if iptest_file.endswith('.txt'):
        # 尝试多种可能的CSV文件路径
        possible_csv_paths = []
        
        # 基础路径
        base_dir = os.path.dirname(iptest_file)
        base_name = os.path.basename(iptest_file)
        
        # 1. 直接替换扩展名
        possible_csv_paths.append(iptest_file.replace('.txt', '.csv'))
        
        # 2. 在相同目录下寻找iptest_*.csv文件
        if 'iptest_' in base_name:
            csv_name = base_name.replace('.txt', '.csv')
            possible_csv_paths.append(os.path.join(base_dir, csv_name))
        
        # 3. 在相同目录下寻找包含"iptest"的CSV文件
        if base_dir:
            for file in os.listdir(base_dir):
                if file.endswith('.csv') and 'iptest' in file.lower():
                    possible_csv_paths.append(os.path.join(base_dir, file))
        
        # 去重
        possible_csv_paths = list(set(possible_csv_paths))
        
        print(f"尝试查找CSV文件，可能的路径:")
        for csv_path in possible_csv_paths:
            print(f"  - {csv_path}")
        
        # 尝试每个可能的路径
        for csv_file_path in possible_csv_paths:
            if os.path.exists(csv_file_path):
                print(f"找到CSV文件: {csv_file_path}")
                return read_download_speeds_from_csv(csv_file_path)
        
        print(f"未找到对应的CSV文件")
        return {}
    else:
        # 如果不是TXT文件，直接尝试作为CSV文件读取
        return read_download_speeds_from_csv(iptest_file)

def read_success_proxies(success_file):
    """读取成功代理文件的数据"""
    success_proxies = {}
    
    if not os.path.exists(success_file):
        print(f"警告: 未找到成功代理文件 {success_file}")
        return success_proxies
    
    try:
        with open(success_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or '#' not in line:
                    continue
                
                # 格式: ip:端口#responseTimems
                proxy_part, rt_part = line.split('#', 1)
                try:
                    # 提取响应时间数字部分
                    rt_num = int(re.sub(r'[^0-9]', '', rt_part))
                    success_proxies[proxy_part] = rt_num
                except:
                    pass
    except Exception as e:
        print(f"读取成功代理文件时出错: {str(e)}")
    
    return success_proxies

def calculate_score(latency_ms, download_speed_str, latency_weight=0.6, speed_weight=0.4):
    """计算综合评分，使用下载速度的原始字符串"""
    # 归一化延迟分数（延迟越低分数越高）
    # 假设延迟范围0-2000ms，2000ms以上得0分
    if latency_ms <= 0:
        latency_score = 100
    elif latency_ms >= 2000:
        latency_score = 0
    else:
        latency_score = 100 * (1 - latency_ms / 2000)
    
    # 从下载速度字符串中提取数字部分用于评分
    speed_num, _ = parse_download_speed_for_display(download_speed_str)
    
    # 归一化速度分数（速度越高分数越高）
    # 假设速度范围0-5000评分值，5000以上得100分
    if speed_num <= 0:
        speed_score = 0
    elif speed_num >= 5000:
        speed_score = 100
    else:
        speed_score = (speed_num * 100) / 5000
    
    # 计算综合得分
    total_score = (latency_score * latency_weight) + (speed_score * speed_weight)
    return round(total_score, 2)

def select_top_proxies(proxy_results, download_speeds, top_n=10):
    """选择综合评分最高的代理"""
    scored_proxies = []
    
    for proxy, data in proxy_results.items():
        latency = data.get('avg_response_time', 9999)
        
        # 获取下载速度字符串，如果没有则默认为空
        speed_str = download_speeds.get(proxy, "")
        
        # 计算综合评分
        score = calculate_score(latency, speed_str)
        
        # 解析下载速度用于显示
        speed_num, speed_display = parse_download_speed_for_display(speed_str)
        
        scored_proxies.append({
            'proxy': proxy,
            'latency': latency,
            'speed_str': speed_str,  # 原始字符串
            'speed_display': speed_display,  # 用于显示的字符串
            'speed_num': speed_num,  # 用于计算的数值
            'score': score
        })
    
    # 按综合评分降序排序
    scored_proxies.sort(key=lambda x: x['score'], reverse=True)
    
    # 返回前N个
    return scored_proxies[:top_n]

def save_top_proxies(top_proxies, output_file):
    """保存最优代理到文件，使用原始下载速度字符串"""
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# 综合最优代理列表（按综合评分排序）\n")
        f.write("# 格式: IP:端口 延迟(ms) 下载速度(原始值) 综合评分\n")
        f.write("#" * 60 + "\n")
        
        for i, proxy_data in enumerate(top_proxies, 1):
            f.write(f"{proxy_data['proxy']} {proxy_data['latency']}ms {proxy_data['speed_str']} {proxy_data['score']}\n")
    
    print(f"📁 最优代理已保存到: {output_file}")

def save_success_proxy(input_file, proxy, avg_response_time, response_times=None):
    """将成功的代理保存到文件，格式为 ip:端口#avg_responseTimems"""
    # 提取基础名称用于结果文件名
    base_name = os.path.basename(input_file).replace('.txt', '')
    dir_name = os.path.dirname(input_file)
    if not dir_name:
        dir_name = '.'
    
    # 尝试从文件名或目录名提取asxxx部分
    if 'as' in dir_name:
        match = re.search(r'as(\d+)', dir_name)
        if match:
            as_num = match.group(0)  # as123
        else:
            as_num = base_name.replace('iptest_', '')  # iptest_as123 -> as123
    else:
        # 从文件名提取asxxx
        match = re.search(r'as\d+', base_name)
        if match:
            as_num = match.group(0)
        else:
            # 使用基础名称作为替代
            as_num = base_name
    
    # 创建结果文件名
    success_file = os.path.join(dir_name, f"{as_num}_success.txt")
    
    # 确保response_time包含单位
    rt_str = str(avg_response_time)
    if not rt_str.endswith('ms'):
        rt_str = f"{rt_str}ms"
    
    # 使用锁保护文件操作
    with file_lock:
        # 读取现有内容
        existing_lines = []
        if os.path.exists(success_file):
            try:
                with open(success_file, 'r', encoding='utf-8') as f:
                    existing_lines = [line.strip() for line in f.readlines() if line.strip()]
            except:
                pass
        
        # 添加新条目，确保包含ms单位
        new_line = f"{proxy}#{rt_str}"
        
        # 如果代理已存在，更新响应时间
        updated = False
        for i, line in enumerate(existing_lines):
            if line.startswith(proxy + '#'):
                existing_lines[i] = new_line
                updated = True
                break
        
        if not updated:
            existing_lines.append(new_line)
        
        # 按响应时间排序
        def get_response_time(line):
            try:
                # 提取响应时间数值部分
                match = re.search(r'#(\d+)', line)
                if match:
                    return int(match.group(1))
                return 99999
            except:
                return 99999
        
        existing_lines.sort(key=get_response_time)
        
        # 写入文件
        with open(success_file, 'w', encoding='utf-8') as f:
            for line in existing_lines:
                f.write(line + '\n')
        
        return success_file

def print_result(proxy, result, count, test_times):
    """打印检测结果"""
    print(f"{count}. 检测: {proxy}")
    
    if 'timeout' in result:
        print("  ⏰ 请求超时")
        return {'status': 'timeout'}
    
    if 'error' in result:
        print(f"  ❌ {result['error']}")
        return {'status': 'failed'}
    
    if result.get('success'):
        avg_rt = result.get('avg_response_time', 0)
        min_rt = result.get('min_response_time', 0)
        max_rt = result.get('max_response_time', 0)
        rt_list = result.get('response_times', [])
        
        # 计算响应时间统计
        if len(rt_list) > 1:
            rt_std = round(statistics.stdev(rt_list), 1)
            print(f"  ✅ 检测 {test_times} 次全部成功")
            print(f"  📊 响应时间: {min_rt}ms ~ {max_rt}ms (平均: {avg_rt}ms, 标准差: {rt_std}ms)")
        else:
            print(f"  ✅ 检测成功")
            print(f"  📊 响应时间: {avg_rt}ms")
        
        # 根据平均响应时间显示评价
        if avg_rt < 100:
            print(f"  ⚡ 评价: 优秀")
        elif avg_rt < 500:
            print(f"  ⏱️  评价: 良好")
        else:
            print(f"  🐢 评价: 较慢")
        
        return {
            'status': 'success', 
            'avg_response_time': avg_rt,
            'response_times': rt_list,
            'min_response_time': min_rt,
            'max_response_time': max_rt
        }
    
    print("  ❓ 响应格式错误")
    return {'status': 'failed'}

def save_results(input_file, total, success_count, failed_count, 
                 timeout_count, working_proxies):
    """保存结果到文件"""
    if total <= 0:
        return
    
    # 提取基础名称用于结果文件名
    base_name = os.path.basename(input_file).replace('.txt', '')
    dir_name = os.path.dirname(input_file)
    if not dir_name:
        dir_name = '.'
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 创建结果目录
    result_dir = os.path.join(dir_name, "results")
    os.makedirs(result_dir, exist_ok=True)
    
    result_file = os.path.join(result_dir, f"{base_name}_results_{timestamp}.txt")
    
    with open(result_file, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write(f"代理检测报告 - {datetime.now()}\n")
        f.write(f"检测文件: {input_file}\n")
        f.write(f"检测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n")
        f.write(f"总计检测: {total}\n")
        f.write(f"成功: {success_count}\n")
        f.write(f"失败: {failed_count}\n")
        f.write(f"超时: {timeout_count}\n")
        
        if total > 0:
            success_rate = (success_count * 100) / total
            f.write(f"成功率: {success_rate:.1f}%\n")
        
        # 保存可用代理到文件
        if working_proxies:
            f.write("\n可用代理 (按平均响应时间排序):\n")
            for proxy_info in working_proxies:
                if isinstance(proxy_info, dict):
                    proxy = proxy_info['proxy']
                    avg_rt = proxy_info.get('avg_response_time', '')
                    rt_list = proxy_info.get('response_times', [])
                    
                    # 确保response_time包含单位
                    rt_str = str(avg_rt)
                    if rt_str and not rt_str.endswith('ms'):
                        rt_str = f"{rt_str}ms"
                    
                    if len(rt_list) > 1:
                        min_rt = proxy_info.get('min_response_time', '')
                        max_rt = proxy_info.get('max_response_time', '')
                        f.write(f"{proxy}#{rt_str} (范围: {min_rt}ms-{max_rt}ms)\n")
                    else:
                        f.write(f"{proxy}#{rt_str}\n")
                else:
                    f.write(f"{proxy_info}\n")
    
    print(f"\n📁 详细结果已保存到: {result_file}")

def process_proxy_line(line, line_num, input_file, counters, test_times):
    """处理单行代理检测"""
    line = line.strip()
    
    # 跳过空行和注释行
    if not line or line.startswith('#'):
        return None
    
    # 分割IP和端口
    parts = line.split()
    if len(parts) < 2:
        print(f"第{line_num}行: 格式错误 - {line}")
        return None
    
    ip = parts[0].strip()
    port = parts[1].strip()
    
    # 检查端口是否有效
    if not re.match(r'^[0-9]+$', port):
        print(f"第{line_num}行: 跳过无效端口 - {ip}:{port}")
        return None
    
    port_num = int(port)
    if port_num < 1 or port_num > 65535:
        print(f"第{line_num}行: 跳过无效端口 - {ip}:{port}")
        return None
    
    proxy = f"{ip}:{port}"
    
    # 多次检测代理
    result = check_proxy_multiple(proxy, test_times)
    
    # 打印结果并获取状态
    with file_lock:
        counters['total'] += 1
        status_result = print_result(proxy, result, counters['total'], test_times)
        
        # 更新计数器
        if status_result['status'] == 'success':
            counters['success'] += 1
            return {
                'proxy': proxy, 
                'avg_response_time': status_result.get('avg_response_time', ''),
                'response_times': status_result.get('response_times', []),
                'min_response_time': status_result.get('min_response_time', ''),
                'max_response_time': status_result.get('max_response_time', ''),
                'status': 'success'
            }
        elif status_result['status'] == 'timeout':
            counters['timeout'] += 1
            counters['failed'] += 1
        else:
            counters['failed'] += 1
    
    return None

def main():
    """主函数"""
    # 检查参数
    if len(sys.argv) < 2:
        print("使用方法:")
        print(f"  {sys.argv[0]} <文件名或编号> [并发数] [检测次数]")
        print("示例:")
        print(f"  {sys.argv[0]} 123                    # 检测 as123/iptest_as123.txt")
        print(f"  {sys.argv[0]} as123                  # 检测 as123/iptest_as123.txt")
        print(f"  {sys.argv[0]} iptest_as123.txt       # 在当前目录查找")
        print(f"  {sys.argv[0]} as123/iptest_as123.txt # 指定完整路径")
        print(f"  {sys.argv[0]} 123 20 3               # 使用20个线程并发，每个IP检测3次")
        sys.exit(1)
    
    # 解析输入参数
    input_file = parse_input_param(sys.argv[1])
    
    # 获取并发数，默认为10
    concurrency = 10
    if len(sys.argv) > 2:
        try:
            concurrency = int(sys.argv[2])
            if concurrency < 1:
                concurrency = 10
            elif concurrency > 50:
                concurrency = 50
        except:
            concurrency = 10
    
    # 获取检测次数，默认为3次
    test_times = 3
    if len(sys.argv) > 3:
        try:
            test_times = int(sys.argv[3])
            if test_times < 1:
                test_times = 3
            elif test_times > 10:
                test_times = 10
        except:
            test_times = 3
    
    # 检查文件是否存在
    if not os.path.isfile(input_file):
        print(f"错误: 文件 '{input_file}' 不存在\n")
        find_proxy_files()
        print("\n请使用以下格式之一:")
        print(f"  {sys.argv[0]} 123                    # 检测 as123/iptest_as123.txt")
        print(f"  {sys.argv[0]} as123                  # 检测 as123/iptest_as123.txt")
        print(f"  {sys.argv[0]} iptest_as123.txt       # 在当前目录查找")
        print(f"  {sys.argv[0]} as123/iptest_as123.txt # 指定完整路径")
        sys.exit(1)
    
    print(f"使用文件: {input_file}")
    print(f"并发数: {concurrency}")
    print(f"每个IP检测次数: {test_times}")
    print("开始检测代理IP...")
    print("=" * 60)
    
    # 计数器
    counters = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'timeout': 0
    }
    
    # 读取文件
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        # 尝试其他编码
        with open(input_file, 'r', encoding='latin-1') as f:
            lines = f.readlines()
    
    # 用于保存成功代理的列表
    success_proxies = []
    
    # 创建线程池执行并发检测
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        
        for line_num, line in enumerate(lines, 1):
            # 提交任务到线程池
            future = executor.submit(
                process_proxy_line, 
                line, line_num, input_file, counters, test_times
            )
            futures.append(future)
        
        # 处理完成的任务
        for future in as_completed(futures):
            result = future.result()
            if result and result['status'] == 'success':
                success_proxies.append(result)
                
                # 保存到成功文件
                if result.get('avg_response_time'):
                    success_file = save_success_proxy(
                        input_file, 
                        result['proxy'], 
                        result['avg_response_time'],
                        result.get('response_times')
                    )
    
    print("=" * 60)
    print("检测完成!")
    print(f"📋 总计检测: {counters['total']}")
    print(f"✅ 成功: {counters['success']}")
    print(f"❌ 失败: {counters['failed']}")
    print(f"⏰ 超时: {counters['timeout']}")
    
    # 计算成功率
    if counters['total'] > 0:
        success_rate = (counters['success'] * 100) / counters['total']
        print(f"📊 成功率: {success_rate:.1f}%")
    
    # 显示可用的代理
    if success_proxies:
        # 按平均响应时间排序
        def get_avg_rt(proxy_info):
            return proxy_info.get('avg_response_time', 99999)
        
        sorted_proxies = sorted(success_proxies, key=get_avg_rt)
        
        print(f"\n🎯 可用代理列表 (共{len(sorted_proxies)}个，按平均响应时间排序):")
        for i, proxy_info in enumerate(sorted_proxies[:20], 1):
            proxy = proxy_info['proxy']
            avg_rt = proxy_info.get('avg_response_time', 'N/A')
            rt_list = proxy_info.get('response_times', [])
            
            # 确保显示时有单位
            rt_str = str(avg_rt)
            if rt_str and not rt_str.endswith('ms'):
                rt_str = f"{rt_str}ms"
            
            if len(rt_list) > 1:
                min_rt = proxy_info.get('min_response_time', '')
                max_rt = proxy_info.get('max_response_time', '')
                print(f"  {i:2d}. {proxy}#{rt_str} (范围: {min_rt}ms-{max_rt}ms)")
            else:
                print(f"  {i:2d}. {proxy}#{rt_str}")
        
        if len(sorted_proxies) > 20:
            print(f"  ... 还有 {len(sorted_proxies) - 20} 个代理未显示")
        
        # 保存最终结果
        save_results(input_file, counters['total'], counters['success'], 
                     counters['failed'], counters['timeout'], sorted_proxies)
        
        # 显示成功文件路径
        if sorted_proxies:
            try:
                # 从第一个成功代理获取响应时间用于测试
                test_proxy = sorted_proxies[0]
                success_file = save_success_proxy(
                    input_file, 
                    test_proxy['proxy'], 
                    test_proxy['avg_response_time'],
                    test_proxy.get('response_times')
                )
                print(f"\n💾 成功代理已保存到: {success_file}")
                print("   格式: ip:端口#avg_responseTimems (按平均响应时间从小到大排序)")
            except:
                pass
        
        # 整合下载速度和延迟数据，选择最优代理
        print("\n" + "=" * 60)
        print("整合下载速度和延迟数据，选择最优代理...")
        
        # 提取基础名称
        base_name = os.path.basename(input_file).replace('.txt', '')
        dir_name = os.path.dirname(input_file)
        if not dir_name:
            dir_name = '.'
        
        # 构建文件路径
        iptest_file = input_file  # iptest_as4766.txt
        success_file = os.path.join(dir_name, f"{base_name.replace('iptest_', '')}_success.txt")
        
        # 读取下载速度数据（从CSV文件）
        print(f"读取下载速度数据: {iptest_file}")
        download_speeds = read_download_speeds(iptest_file)
        print(f"找到 {len(download_speeds)} 个代理的下载速度数据")
        
        # 如果有下载速度数据，显示一些示例
        if download_speeds:
            print("下载速度数据示例 (前5个):")
            count = 0
            for proxy, speed_str in list(download_speeds.items())[:5]:
                print(f"  {proxy}: {speed_str}")
                count += 1
            if len(download_speeds) > 5:
                print(f"  ... 还有 {len(download_speeds) - 5} 个代理的下载速度数据")
        
        # 读取成功代理的延迟数据
        print(f"读取延迟数据: {success_file}")
        success_proxies_dict = {p['proxy']: p['avg_response_time'] for p in success_proxies}
        print(f"找到 {len(success_proxies_dict)} 个成功代理的延迟数据")
        
        # 选择最优代理
        print(f"正在计算综合评分...")
        proxy_results = {}
        for proxy, latency in success_proxies_dict.items():
            proxy_results[proxy] = {'avg_response_time': latency}
        
        top_proxies = select_top_proxies(proxy_results, download_speeds, top_n=10)
        
        # 显示和保存最优代理
        print(f"\n🏆 综合最优代理 (前10个):")
        print("排名 | 代理 | 延迟(ms) | 下载速度 | 综合评分")
        print("-" * 60)
        
        for i, proxy_data in enumerate(top_proxies, 1):
            print(f"{i:2d}. {proxy_data['proxy']} | {proxy_data['latency']}ms | {proxy_data['speed_str']} | {proxy_data['score']}")
        
        # 保存最优代理到文件
        top_proxies_file = os.path.join(dir_name, f"{base_name.replace('iptest_', '')}_top10.txt")
        save_top_proxies(top_proxies, top_proxies_file)
        
    else:
        print("\n⚠️ 没有找到可用的代理")

if __name__ == "__main__":
    main()