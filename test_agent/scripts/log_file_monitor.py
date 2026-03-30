"""
Log File Monitor - 监控 Chrome/Edge 日志文件
用于捕获 native-ec 的状态变化和 profile filter 结果
"""

import os
import re
from typing import Optional, List, Dict


# Pattern examples from Edge log:
# VERBOSE1: [pid:tid:date/time:VERBOSE1:...wallet_checkout_trigger_funnel_manager.cc:196]
#   wallet-ec trigger funnel domain nike.com site type: TopSite filter: 3 failed_reason: 29
# VERBOSE2: [pid:tid:date/time:VERBOSE2:...shipping_address_form.cc:126]
#   ec-trigger profile 16f1e61a-9045-4379-85ed-ee006b3cee3c failed reason: 29
# VERBOSE2: [pid:tid:date/time:VERBOSE2:...shipping_address_form.cc:149]
#   ec-trigger profile 950c13f6-870a-4b2d-b829-23d072c0b595 is valid profile
# VERBOSE1: native-ec notify state=AutofillSucceeded

_GUID_RE = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
_TS_RE = r'\d{6}\.\d{3}'


def _extract_timestamp(line: str) -> str:
    m = re.search(_TS_RE, line)
    return m.group(0) if m else 'unknown'


class LogFileMonitor:
    """Chrome/Edge 日志文件监控器"""

    def __init__(self, log_file_path: str):
        self.log_file_path = log_file_path
        self.last_position = 0
        self.states_history: List[Dict] = []
        self.profile_filter_history: List[Dict] = []

    def _parse_line(self, line: str) -> Optional[Dict]:
        """解析日志行，返回 event dict 或 None。

        event types:
          - 'autofill_state':  native-ec notify state=XXX
          - 'profile_failed':  ec-trigger profile <guid> failed reason: <int>
          - 'profile_valid':   ec-trigger profile <guid> is valid profile
          - 'funnel_failed':   wallet-ec trigger funnel ... failed_reason: <int>
        """
        ts = _extract_timestamp(line)

        # native-ec notify state=AutofillSucceeded
        m = re.search(r'native-ec notify state=([A-Za-z]+)', line)
        if m:
            return {'type': 'autofill_state', 'state_name': m.group(1), 'timestamp_str': ts}

        # ec-trigger profile <guid> failed reason: <int>
        m = re.search(r'ec-trigger profile (' + _GUID_RE + r') failed reason:\s*(\d+)', line)
        if m:
            return {'type': 'profile_failed', 'guid': m.group(1),
                    'failed_reason': int(m.group(2)), 'timestamp_str': ts}

        # ec-trigger profile <guid> is valid profile
        m = re.search(r'ec-trigger profile (' + _GUID_RE + r') is valid profile', line)
        if m:
            return {'type': 'profile_valid', 'guid': m.group(1), 'timestamp_str': ts}

        # wallet-ec trigger funnel domain <domain> ... failed_reason: <int>
        m = re.search(r'wallet-ec trigger funnel domain (\S+).*?failed_reason:\s*(\d+)', line)
        if m:
            return {'type': 'funnel_failed', 'domain': m.group(1),
                    'failed_reason': int(m.group(2)), 'timestamp_str': ts}

        return None

    def check_new_states(self) -> List[Dict]:
        """检查新的日志事件，返回本次新增的所有事件列表（兼容旧接口）。

        为向后兼容，autofill_state 类型的事件也会写入 states_history，
        其 state_name 字段与旧版一致。
        profile_failed / profile_valid / funnel_failed 写入 profile_filter_history。
        """
        if not os.path.exists(self.log_file_path):
            return []

        new_events: List[Dict] = []
        try:
            with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self.last_position)
                new_lines = f.readlines()
                self.last_position = f.tell()

                for line in new_lines:
                    event = self._parse_line(line)
                    if not event:
                        continue
                    new_events.append(event)
                    if event['type'] == 'autofill_state':
                        self.states_history.append(event)
                    else:
                        self.profile_filter_history.append(event)

        except Exception as e:
            print(f"Error reading log file: {e}")

        return new_events

    def get_filter_summary(self) -> Dict:
        """返回 profile_filter_history 的摘要：哪些 guid 被过滤，哪些有效。"""
        failed = {e['guid']: e['failed_reason']
                  for e in self.profile_filter_history if e['type'] == 'profile_failed'}
        # deduplicate: same guid can appear many times if multiple profiles were checked
        valid = list(dict.fromkeys(
            e['guid'] for e in self.profile_filter_history if e['type'] == 'profile_valid'
        ))
        return {'failed': failed, 'valid': valid}
