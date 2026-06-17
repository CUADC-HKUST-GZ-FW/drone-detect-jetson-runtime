# WebUI Tests

Run from the repository root:

```bash
python3 webui/tests/e2e_smoke.py
```

The test suite uses only Python standard library modules. It starts the WebUI on random localhost ports and validates:

- health endpoint
- static UI load
- OpenAPI endpoint
- config read/write
- allowlisted run execution
- token authentication
- CORS preflight
- request body limit
- refusal to bind externally without a token

