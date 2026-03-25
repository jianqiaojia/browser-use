"""
Aggressive markdown stripping patch for litellm proxy

Ensures ALL JSON responses from Claude get stripped of markdown, regardless of code path.
"""
from pydantic import BaseModel


def patch_aggressive_strip():
	"""Patch model_validate_json to strip markdown before parsing"""
	original_validate_json = BaseModel.model_validate_json

	@classmethod
	def patched_validate_json(cls, json_data, **kwargs):
		"""Strip markdown fences before validation"""
		if isinstance(json_data, str):
			# Strip markdown code fences
			cleaned = json_data.strip()
			if cleaned.startswith('```json') and cleaned.endswith('```'):
				json_data = cleaned[7:-3].strip()
			elif cleaned.startswith('```') and cleaned.endswith('```'):
				json_data = cleaned[3:-3].strip()

		return original_validate_json.__func__(cls, json_data, **kwargs)

	BaseModel.model_validate_json = patched_validate_json


# Apply patch immediately on import
patch_aggressive_strip()
print("[INFO] Applied aggressive markdown stripping patch - ALL JSON will be cleaned")
