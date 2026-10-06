import importlib.util
from pathlib import Path
import unittest
import sys

spec = importlib.util.spec_from_file_location('linux_census', Path(__file__).parents[1] / 'collectors/linux_census.py')
linux = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linux)


class LinuxParserTests(unittest.TestCase):
    def test_output_is_bounded_without_a_target_spool(self):
        result = linux.run([sys.executable, '-c', 'import sys; sys.stdout.buffer.write(b"x" * 4194304)'])
        self.assertEqual(result['status'], 'truncated')
        self.assertNotIn('data', result)

    def test_query_timeout_and_success(self):
        self.assertEqual(linux.run([sys.executable, '-c', 'import time; time.sleep(1)'], timeout=.05)['status'], 'timeout')
        self.assertEqual(linux.run([sys.executable, '-c', 'print("ok")'])['data'], 'ok')

    def test_tcp_snapshot_does_not_infer_initiator(self):
        text = 'ESTAB 0 0 192.0.2.10:53311 192.0.2.20:5432 users:(("python3",pid=113,fd=4))'
        item = linux.parse_sockets(text)[0]
        self.assertEqual(item['process'], 'python3')
        self.assertEqual(item['remote_port'], 5432)
        self.assertEqual(item['initiator'], 'unknown')
        self.assertNotIn('command_line', item)

    def test_ipv6_listener_and_unknown_process(self):
        item = linux.parse_sockets('LISTEN 0 128 [::]:22 [::]:*')[0]
        self.assertEqual(item['local_address'], '::')
        self.assertEqual(item['local_port'], 22)
        self.assertIsNone(item['remote_port'])
        self.assertIsNone(item['process'])


if __name__ == '__main__':
    unittest.main()
