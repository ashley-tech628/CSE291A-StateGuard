import json

from stateguard.model_adapter import ModelAdapter

adapter = ModelAdapter()

result = adapter.generate_json(
    system_prompt="Return a JSON object with the field ok set to true.",
    input_data={"task": "connection test"},
)

print(json.dumps(result, indent=2, ensure_ascii=False))
