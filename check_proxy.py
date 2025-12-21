#!/usr/bin/env python3
"""
代理检测脚本 (Python版本)
从指定文件读取代理IP:端口，使用在线服务检测代理可用性
支持并发检测并按响应时间排序保存成功结果
"""

import os
import sys
import re
import json
import time
import threading
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

def check_proxy(proxy, line_num, timeout=15):
    """检测单个代理"""
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

def save_success_proxy(input_file, proxy, response_time):
    """将成功的代理保存到文件，格式为 ip:端口#responseTimems"""
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
    if response_time and isinstance(response_time, (int, float, str)):
        rt_str = str(response_time)
        # 如果response_time已经是纯数字，添加ms单位
        if re.match(r'^\d+$', rt_str):
            rt_str = f"{rt_str}ms"
        # 如果response_time是数字但没有单位，添加ms单位
        elif re.match(r'^\d+\.?\d*$', rt_str):
            rt_str = f"{rt_str}ms"
        response_time = rt_str
    
    # 获取响应时间的数值部分用于排序
    try:
        # 提取数字部分用于排序
        rt_num = int(re.sub(r'[^0-9]', '', str(response_time)))
    except:
        rt_num = 99999  # 如果无法解析，放在最后
    
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
        new_line = f"{proxy}#{response_time}"
        
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

def print_result(proxy, result, count, line_num):
    """打印检测结果"""
    print(f"{count}. 检测: {proxy}")
    
    if 'timeout' in result:
        print("  ⏰ 请求超时")
        return {'status': 'timeout'}
    
    if 'error' in result:
        print(f"  ❌ {result['error']}")
        return {'status': 'failed'}
    
    success = result.get('success')
    response_time = result.get('response_time')
    error_msg = result.get('error_msg')
    
    if success in [True, 'true', 'True']:
        print("  ✅ success: true")
        
        if response_time:
            # 确保response_time有单位
            rt_str = str(response_time)
            if not rt_str.endswith('ms'):
                rt_str = f"{rt_str}ms"
            
            # 根据响应时间显示不同评价
            try:
                rt_num = int(re.sub(r'[^0-9]', '', str(response_time)))
                if rt_num < 100:
                    print(f"  ⚡ responseTime: {rt_str} (优秀)")
                elif rt_num < 500:
                    print(f"  ⏱️  responseTime: {rt_str} (良好)")
                else:
                    print(f"  🐢 responseTime: {rt_str} (较慢)")
            except:
                print(f"  ⏱️  responseTime: {rt_str}")
            # 返回带单位的response_time
            return {'status': 'success', 'response_time': rt_str}
        else:
            print("  ⏱️  responseTime: 不可用")
            return {'status': 'success', 'response_time': 'N/A'}
    
    elif success in [False, 'false', 'False']:
        print("  ❌ success: false")
        if error_msg:
            print(f"  💬 错误信息: {error_msg}")
        return {'status': 'failed'}
    
    else:
        print("  ❓ 响应格式错误")
        if 'raw_response' in result:
            raw = str(result['raw_response'])[:100]
            print(f"  原始响应: {raw}...")
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
        f.write("=" * 50 + "\n")
        f.write(f"代理检测报告 - {datetime.now()}\n")
        f.write(f"检测文件: {input_file}\n")
        f.write(f"检测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 50 + "\n")
        f.write(f"总计检测: {total}\n")
        f.write(f"成功: {success_count}\n")
        f.write(f"失败: {failed_count}\n")
        f.write(f"超时: {timeout_count}\n")
        
        if total > 0:
            success_rate = (success_count * 100) // total
            f.write(f"成功率: {success_rate}%\n")
        
        # 保存可用代理到文件
        if working_proxies:
            f.write("\n可用代理:\n")
            for proxy_info in working_proxies:
                if isinstance(proxy_info, dict):
                    proxy = proxy_info['proxy']
                    rt = proxy_info.get('response_time', '')
                    # 确保response_time包含单位
                    if rt and not rt.endswith('ms'):
                        rt = f"{rt}ms"
                    f.write(f"{proxy}#{rt}\n")
                else:
                    f.write(f"{proxy_info}\n")
    
    print(f"\n📁 详细结果已保存到: {result_file}")

def process_proxy_line(line, line_num, input_file, counters):
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
    
    # 检测代理
    result = check_proxy(proxy, line_num)
    
    # 打印结果并获取状态
    with file_lock:
        counters['total'] += 1
        status_result = print_result(proxy, result, counters['total'], line_num)
        
        # 更新计数器
        if status_result['status'] == 'success':
            counters['success'] += 1
            return {
                'proxy': proxy, 
                'response_time': status_result.get('response_time', ''),
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
        print(f"  {sys.argv[0]} <文件名或编号> [并发数]")
        print("示例:")
        print(f"  {sys.argv[0]} 123                    # 检测 as123/iptest_as123.txt")
        print(f"  {sys.argv[0]} as123                  # 检测 as123/iptest_as123.txt")
        print(f"  {sys.argv[0]} iptest_as123.txt       # 在当前目录查找")
        print(f"  {sys.argv[0]} as123/iptest_as123.txt # 指定完整路径")
        print(f"  {sys.argv[0]} 123 20                 # 使用20个线程并发检测")
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
            elif concurrency > 100:
                concurrency = 100
        except:
            concurrency = 10
    
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
    print("开始检测代理IP...")
    print("=" * 50)
    
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
                line, line_num, input_file, counters
            )
            futures.append(future)
        
        # 处理完成的任务
        for future in as_completed(futures):
            result = future.result()
            if result and result['status'] == 'success':
                success_proxies.append(result)
                
                # 保存到成功文件
                if result.get('response_time'):
                    success_file = save_success_proxy(
                        input_file, 
                        result['proxy'], 
                        result['response_time']
                    )
    
    print("=" * 50)
    print("检测完成!")
    print(f"📋 总计检测: {counters['total']}")
    print(f"✅ 成功: {counters['success']}")
    print(f"❌ 失败: {counters['failed']}")
    print(f"⏰ 超时: {counters['timeout']}")
    
    # 计算成功率
    if counters['total'] > 0:
        success_rate = (counters['success'] * 100) // counters['total']
        print(f"📊 成功率: {success_rate}%")
    
    # 显示可用的代理
    if success_proxies:
        # 按响应时间排序
        def get_rt(proxy_info):
            try:
                rt_str = str(proxy_info.get('response_time', ''))
                return int(re.sub(r'[^0-9]', '', rt_str))
            except:
                return 99999
        
        sorted_proxies = sorted(success_proxies, key=get_rt)
        
        print(f"\n🎯 可用代理列表 (共{len(sorted_proxies)}个，按响应时间排序):")
        for i, proxy_info in enumerate(sorted_proxies, 1):
            proxy = proxy_info['proxy']
            rt = proxy_info.get('response_time', 'N/A')
            # 确保显示时有单位
            if rt and not rt.endswith('ms'):
                rt = f"{rt}ms"
            print(f"  {i}. {proxy}#{rt}")
        
        # 保存最终结果
        save_results(input_file, counters['total'], counters['success'], 
                     counters['failed'], counters['timeout'], sorted_proxies)
        
        # 显示成功文件路径
        if sorted_proxies:
            # 尝试获取成功文件路径
            try:
                # 从第一个成功代理获取响应时间用于测试
                test_proxy = sorted_proxies[0]
                success_file = save_success_proxy(
                    input_file, 
                    test_proxy['proxy'], 
                    test_proxy['response_time']
                )
                print(f"\n💾 成功代理已保存到: {success_file}")
                print("   格式: ip:端口#responseTimems (按响应时间从小到大排序)")
            except:
                pass
    else:
        print("\n⚠️ 没有找到可用的代理")

if __name__ == "__main__":
    main()