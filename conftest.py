# Makes the project root importable so tests can `from app.main import app`.
import os

# Test collection imports the app and configures its process-global provider.
# Never send test traces to a backend inherited from a developer's environment.
# Export integration tests supply their own explicit loopback settings.
for _name in tuple(os.environ):
    if _name.startswith("OTEL_"):
        del os.environ[_name]
