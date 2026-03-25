"""
Log File Monitor - 监控 Chrome/Edge 日志文件
用于捕获 native-ec 的状态变化
"""

import os
import re
from typing import Optional, List, Dict


class LogFileMonitor:
    """Chrome/Edge 日志文件监控器 - 精简版"""
    
    def __init__(self, log_file_path: str):
        """初始化日志监控器"""
        self.log_file_path = log_file_path
        self.last_position = 0
        self.states_history = []
    
    def _parse_state_from_line(self, line: str) -> Optional[Dict]:
        """从日志行解析状态信息"""
        # 匹配: native-ec notify state=AutofillSucceeded
        pattern = r'native-ec notify state=([A-Za-z]+)'
        match = re.search(pattern, line)
        
        if match:
            state_name = match.group(1)
            
            # 提取时间戳
            time_match = re.search(r'\[.*?(\d{6}\.\d{3}):', line)
            timestamp_str = time_match.group(1) if time_match else 'unknown'
            
            return {
                'state_name': state_name,
                'timestamp_str': timestamp_str
            }
        
        return None
    
    def check_new_states(self) -> List[Dict]:
        """检查新的状态变化"""
        if not os.path.exists(self.log_file_path):
            return []
        
        new_states = []
        
        try:
            with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self.last_position)
                new_lines = f.readlines()
                self.last_position = f.tell()
                
                for line in new_lines:
                    state = self._parse_state_from_line(line)
                    if state:
                        new_states.append(state)
                        self.states_history.append(state)
        
        except Exception as e:
            print(f"Error reading log file: {e}")
        
        return new_states