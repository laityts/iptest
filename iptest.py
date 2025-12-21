import os
import csv
import subprocess
import argparse

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='代理检查工具')
    parser.add_argument('filename', help='文件名或编号（支持.csv或.txt格式）')
    return parser.parse_args()

def normalize_base_name(input_arg):
    """将输入参数统一转换为 asxxx 格式的基础名"""
    # 分离文件名和扩展名
    name_without_ext = os.path.splitext(input_arg)[0]
    
    # 如果是以as开头，保持原样（去掉可能的asas情况）
    if name_without_ext.startswith('as'):
        # 处理 asasxxx 的情况，只保留一个 as
        if name_without_ext.startswith('asas'):
            return name_without_ext[2:]  # 去掉开头的 as
        return name_without_ext
    
    # 如果不是以as开头，添加as前缀
    # 如果已经是纯数字或带as格式，直接添加as
    if name_without_ext.isdigit():
        return f"as{name_without_ext}"
    else:
        # 对于非数字的其他格式，也添加as前缀
        return f"as{name_without_ext}"

# 解析命令行参数
args = parse_arguments()
input_arg = args.filename.strip()

# 获取基础名（统一格式）
base_name = normalize_base_name(input_arg)

# 尝试查找文件，尝试多种可能的文件名组合
possible_files = []
search_paths = []

# 如果输入包含路径，分离路径和文件名
input_dir = os.path.dirname(input_arg)
input_file = os.path.basename(input_arg)

# 构建可能的文件名列表
possible_filenames = [
    input_arg,  # 原始输入
    f"{base_name}.csv",
    f"{base_name}.txt",
]

# 如果需要，也可以尝试不带as的版本
if input_arg.isdigit():
    # 如果是纯数字，也可以尝试 as+数字 和 直接数字
    possible_filenames.extend([f"{input_arg}.csv", f"{input_arg}.txt"])

input_filename = None
for filename in possible_filenames:
    if os.path.exists(filename):
        input_filename = filename
        break

if not input_filename:
    print(f"找不到文件，尝试了以下文件名:")
    for filename in possible_filenames:
        print(f"  - {filename}")
    exit(1)

# 创建输出文件夹（统一使用 asxxx 格式）
output_folder = base_name
if not os.path.exists(output_folder):
    os.makedirs(output_folder)
    print(f"已创建输出文件夹: {output_folder}")

# 根据基础名动态生成其他文件名（存放在输出文件夹下）
PROXY_FILE = os.path.join(output_folder, f'{base_name}.txt')
IPTEST_CSV_FILE = os.path.join(output_folder, f'iptest_{base_name}.csv')
IPTEST_TXT_FILE = os.path.join(output_folder, f'iptest_{base_name}.txt')

print("配置完成:")
print(f"  输入文件: {input_filename}")
print(f"  基础名: {base_name}")
print(f"  输出文件夹: {output_folder}")
print("=" * 60)

# 步骤0: 删除之前生成的旧文件
def cleanup_old_files():
    """删除之前生成的旧文件"""
    files_to_remove = [PROXY_FILE, IPTEST_CSV_FILE, IPTEST_TXT_FILE]
    
    for file_path in files_to_remove:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"已删除旧文件: {file_path}")
        except Exception as e:
            print(f"删除文件 {file_path} 时发生异常: {str(e)}")

# 执行清理
cleanup_old_files()

# 步骤1: 从输入文件提取 ip 和 port 并保存到 {base_name}.txt
try:
    if not os.path.exists(input_filename):
        print(f"{input_filename} 不存在，无法提取代理。")
        exit(1)
    
    file_extension = os.path.splitext(input_filename)[1].lower()
    
    if file_extension == '.csv':
        # 处理CSV文件
        with open(input_filename, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            headers = next(reader, None)  # 读取表头行
            if headers is None:
                print("CSV文件为空。")
                exit(1)
            
            # 查找列索引，支持多种中英文列名格式
            ip_col_idx = -1
            port_col_idx = -1
            
            for i, header in enumerate(headers):
                header_lower = header.lower().strip()
                
                # 匹配IP相关列名
                if header_lower in ['ip', 'ip地址', 'ip 地址', 'ip address', 'ip_address']:
                    ip_col_idx = i
                # 匹配端口相关列名  
                elif header_lower in ['port', '端口', '端口号']:
                    port_col_idx = i
            
            # 如果没找到标准列名，尝试使用前两列作为默认
            if ip_col_idx == -1 and len(headers) > 0:
                ip_col_idx = 0
                print(f"未找到IP列，使用第一列 '{headers[0]}' 作为IP地址")
            if port_col_idx == -1 and len(headers) > 1:
                port_col_idx = 1
                print(f"未找到端口列，使用第二列 '{headers[1]}' 作为端口")
            
            if ip_col_idx == -1 or port_col_idx == -1:
                print("CSV中未找到 'ip' 和 'port' 列（忽略大小写）。")
                exit(1)
            
            # 读取数据行并写入 {base_name}.txt
            valid_count = 0
            with open(PROXY_FILE, 'w', encoding='utf-8') as f:
                for row in reader:
                    if len(row) > max(ip_col_idx, port_col_idx):
                        ip = row[ip_col_idx].strip()
                        port = row[port_col_idx].strip()
                        
                        # 直接写入，不做验证
                        if ip and port:
                            f.write(f"{ip} {port}\n")
                            valid_count += 1
            
            if valid_count == 0:
                print("CSV中无IP和端口数据。")
                exit(1)
            
            print(f"已将 {valid_count} 个IPs和ports提取到 {PROXY_FILE}")
                
    elif file_extension == '.txt':
        # 处理TXT文件，假设格式为 "ip port" 或 "ip:port"
        valid_count = 0
        with open(input_filename, 'r', encoding='utf-8') as infile, \
             open(PROXY_FILE, 'w', encoding='utf-8') as outfile:
            for line in infile:
                line = line.strip()
                if not line:
                    continue
                
                # 处理 "ip port" 或 "ip:port" 格式
                if ' ' in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        ip, port = parts[0], parts[1]
                    else:
                        continue
                elif ':' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        ip, port = parts[0], parts[1]
                    else:
                        continue
                else:
                    continue
                
                # 直接写入，不做验证
                if ip and port:
                    outfile.write(f"{ip} {port}\n")
                    valid_count += 1
        
        if valid_count == 0:
            print("TXT文件中无IP和端口数据。")
            exit(1)
        
        print(f"已将 {valid_count} 个IPs和ports从 {input_filename} 提取到 {PROXY_FILE}")
    else:
        print(f"不支持的文件格式: {file_extension}，请使用.csv或.txt文件")
        exit(1)
        
except FileNotFoundError:
    print(f"文件 {input_filename} 不存在。")
    exit(1)
except csv.Error as e:
    print(f"读取CSV文件时发生错误: {str(e)}")
    exit(1)
except Exception as e:
    print(f"提取代理时发生异常: {str(e)}")
    exit(1)

# 步骤2: 执行 ./iptest 并处理生成的 CSV
print("正在执行 ./iptest 命令...")
try:
    # 构建iptest命令
    iptest_command = ['./iptest', '-file', PROXY_FILE, '-outfile', IPTEST_CSV_FILE, '-tls=true']
    
    # 执行iptest命令
    process = subprocess.Popen(iptest_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
    
    # 实时读取并显示输出
    print("=" * 50)
    print("iptest 执行输出:")
    print("=" * 50)
    
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            print(output.strip())
    
    returncode = process.poll()
    
    if returncode != 0:
        print(f"执行 ./iptest 失败，返回码: {returncode}")
    else:
        print("./iptest 执行成功")
        
        # 检查是否生成了 CSV 文件
        if os.path.exists(IPTEST_CSV_FILE):
            print(f"检测到 {IPTEST_CSV_FILE} 文件，开始提取代理信息...")
            
            # 从 iptest CSV 提取 ip 和端口，保存到 iptest_{base_name}.txt
            seen_proxies = set()  # 用于去重的集合
            valid_count = 0
            with open(IPTEST_CSV_FILE, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                headers = next(reader, None)  # 读取表头行
                
                if headers and len(headers) >= 9:  # 确保有足够的列
                    # 查找IP、端口列的位置
                    ip_col_idx = 0
                    port_col_idx = 1
                    
                    # 写入 iptest_{base_name}.txt，去重
                    with open(IPTEST_TXT_FILE, 'w', encoding='utf-8') as f:
                        for row in reader:
                            if len(row) > max(ip_col_idx, port_col_idx):
                                ip = row[ip_col_idx].strip()
                                port = row[port_col_idx].strip()
                                
                                if ip and port:
                                    proxy_key = f"{ip}:{port}"  # 创建唯一标识符
                                    if proxy_key not in seen_proxies:  # 检查是否重复
                                        seen_proxies.add(proxy_key)
                                        f.write(f"{ip} {port}\n")
                                        valid_count += 1
                    
                    print(f"从 {IPTEST_CSV_FILE} 提取了 {valid_count} 个代理到 {IPTEST_TXT_FILE}")
                else:
                    print(f"{IPTEST_CSV_FILE} 文件格式不正确")
        else:
            print(f"未找到 {IPTEST_CSV_FILE} 文件")
            
except subprocess.TimeoutExpired:
    print("./iptest 执行超时")
except FileNotFoundError:
    print("未找到 ./iptest 命令")
except Exception as e:
    print(f"执行 ./iptest 时发生异常: {str(e)}")

# 显示最终结果
print("\n" + "="*80)
print("代理检查完成！")
print("="*80)

# 显示提取的代理
try:
    if os.path.exists(IPTEST_TXT_FILE):
        with open(IPTEST_TXT_FILE, 'r', encoding='utf-8') as f:
            proxies = [line.strip() for line in f if line.strip()]
        
        if proxies:
            print(f"\n有效代理 (共 {len(proxies)} 个):")
            for i, proxy in enumerate(proxies[:20], 1):  # 只显示前20个
                print(f"  {i:2d}. {proxy}")
            
            if len(proxies) > 20:
                print(f"  ... 还有 {len(proxies) - 20} 个代理未显示")
        else:
            print("\n无有效代理")
    else:
        print("\n未生成有效代理文件")
except Exception as e:
    print(f"显示结果时发生异常: {str(e)}")

print("="*80)
print(f"输出文件夹: {output_folder}")
print(f"提取的代理列表: {PROXY_FILE}")
print(f"iptest生成的CSV: {IPTEST_CSV_FILE}")
print(f"提取的有效代理: {IPTEST_TXT_FILE}")
print("="*80)