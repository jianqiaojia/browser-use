"""
Log helper utilities for test execution.

Provides logging utilities including TeeLogger for dual console/file output.
"""
import sys
from pathlib import Path
from datetime import datetime


class TeeLogger:
	"""Writes to both console and file simultaneously"""

	def __init__(self, file_path: Path | str):
		"""Initialize TeeLogger with file path.

		Args:
			file_path: Path to log file
		"""
		self.terminal = sys.stdout
		self.log = open(file_path, 'w', encoding='utf-8', errors='replace')

	def write(self, message: str) -> None:
		"""Write message to both terminal and file.

		Args:
			message: Message to write
		"""
		# Write to terminal with error handling for unicode
		try:
			self.terminal.write(message)
		except UnicodeEncodeError:
			# Fallback: replace problematic characters
			self.terminal.write(
				message.encode(self.terminal.encoding, errors='replace').decode(self.terminal.encoding)
			)

		# Write to log file (UTF-8, no issues)
		self.log.write(message)
		self.log.flush()  # Ensure immediate write

	def flush(self) -> None:
		"""Flush both terminal and file buffers."""
		self.terminal.flush()
		self.log.flush()

	def close(self) -> None:
		"""Close log file."""
		self.log.close()


def setup_logging(log_dir: Path, prefix: str = "batch_run") -> tuple[TeeLogger, Path]:
	"""Setup log file with console output duplication.

	Args:
		log_dir: Directory to store log files
		prefix: Log file name prefix (default: "batch_run")

	Returns:
		Tuple of (TeeLogger instance, log file path)
	"""
	log_dir.mkdir(parents=True, exist_ok=True)
	timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
	log_file = log_dir / f"{prefix}_{timestamp}.log"

	tee = TeeLogger(log_file)
	return tee, log_file
