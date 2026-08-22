# English Lab V2.6 — Consolidation & Deployment

## Goal
Consolidate V2.1–V2.5 into one production entrypoint and remove legacy API dependencies.

## Deployment contract
- Hugging Face Space SDK: Gradio
- Local model: Qwen/Qwen3-4B
- AI Teacher: local Transformers inference
- No OpenAI/DeepSeek/Qwen API
- SQLite for learning state
- ZeroGPU-compatible GPU functions

## ZeroGPU requirements
- Space hardware: ZeroGPU
- `spaces.GPU` around GPU-dependent inference
- Keep model placement/loading compatible with the current ZeroGPU documentation
- Avoid `torch.compile`

## Acceptance checks
1. `python app.py` starts the complete app.
2. No imports or environment variables for OpenAI/DeepSeek/Qwen API.
3. Listening session, transcript reveal/hide, speaking, AI Teacher, quiz, vocabulary review and progress are reachable from one UI.
4. SQLite database initializes automatically.
5. AI Teacher failure does not crash the whole app; user gets a clear error.
6. CPU fallback remains available for local development.
