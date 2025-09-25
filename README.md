# meme-alpha

Pair-programming workflow with patches.

## Setup
1. Create a virtualenv (optional) and install deps:
   ```bash
   pip install -r requirements.txt
   ```
2. Create your local `.env` from the template:
   ```bash
   copy .env.example .env
   ```
   > Fill in real values. `.env` is gitignored.

## Patch workflow
When requesting a change, assistant will send a unified diff. Apply it with:
```bash
git apply patch.diff
```
If you ever see conflicts:
```bash
git apply --reject patch.diff
```

## Common commands
```bash
git status
git add .
git commit -m "message"
git push
```

