# Network behavior

This page is the auditable list of what the Undisclosed desktop app and its
local brain can connect to, and what opens each connection. It covers the app,
not the marketing site. The site loads Google Analytics only after you allow it.

**The default is no outbound connection.** The editor and the brain are two
local processes. With a local model, the agent loop works with the network
blocked. Everything below is opt-in: you add a key, connect a service, install
an extension, or name a sync host.

## Connections

| Connection | Host | Opens when | What can leave |
| --- | --- | --- | --- |
| Brain (local) | `127.0.0.1:5001` | Always, while the app runs | Editor and brain traffic on loopback. No network hop. |
| Local model server | `localhost:11434` (Ollama), `localhost:1234` (LM Studio), or the port you set | When the selected model is local | The prompt and tool context, to the model process on your machine. |
| Model provider | See the provider table below | Only while a turn uses a cloud model | The assembled prompt, tool schemas, the file excerpts the agent read, and the model's replies. |
| GitHub | `api.github.com` | Only when a GitHub tool runs and `GITHUB_ACCESS_TOKEN` is set | Repository, issue, branch and pull-request calls. |
| Google Calendar | `googleapis.com`, `oauth2.googleapis.com` | Only when the Calendar toolkit is used with an OAuth token | Calendar reads and writes, and token refresh. |
| Google Drive | `www.googleapis.com` (through the Drive MCP server) | Only when the Drive toolkit is used | File search, read, and upload calls. |
| Gmail | `gmail.googleapis.com` (through the Gmail MCP server) | Only when the Gmail toolkit is used | Message search, read, send, and label calls. |
| Notion | `mcp.notion.com` | Only after you add the Notion MCP server and connect it | The Notion searches and writes you ask for. |
| Figma | `api.figma.com` | Only when a Figma tool runs with a token | File and node reads. |
| Slack | `slack.com/api` | Only when a Slack tool runs with a bot or user token | Channel, message, thread and file calls. |
| MongoDB | The cluster URI you configure | Only when a Mongo tool runs | Read queries, and the gated `mongo_eval` escape hatch. |
| Web search | `www.googleapis.com/customsearch/v1` or `api.exa.ai` | Only when the task asks for a search | The query text. |
| Browser and crawler | The URL you open | Only when the task asks for a page | The request to that page, including cookies the page sets. |
| Other connectors | The service's own API host | Only when that connector is enabled with credentials | The calls the agent makes through that connector. This covers X/Twitter, LinkedIn, Reddit, WhatsApp, Lark and similar toolkits. |
| MCP servers | The endpoint you add | Only for servers you configure | Whatever that server's tools send. The server, not Undisclosed, decides. |
| Extension gallery | `open-vsx.org` (default) or the gallery you configure | Only when you search for or install an extension | Extension search and download requests. |
| Deploy | None in practice. The toolkit ships with `space.undisclosed.ai:8080`, a placeholder that does not resolve. | Not tested; treat it as unavailable | The HTML or site content you pass to the deploy tool. |
| Step sync | The `SERVER_URL` you set; unset by default | Untested; off unless `SERVER_URL` is set | Chat step events for that task. |
| Langfuse metrics | `us.cloud.langfuse.com` or your base URL | Only when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set | Workforce metrics, not file contents. Off by default. |
| Undisclosed-hosted chat | None | Never | No account, no chat relay, no Undisclosed server between you and the model. |

## Model providers

These are the built-in cloud provider hosts. If you add a custom OpenAI-compatible
endpoint, that host replaces the provider host in the table.

| Provider | Host |
| --- | --- |
| OpenAI | `api.openai.com` |
| Anthropic | `api.anthropic.com` |
| Gemini | `generativelanguage.googleapis.com` |
| xAI / Grok | `api.x.ai` |
| DeepSeek | `api.deepseek.com` |
| Mistral | `api.mistral.ai` |
| OpenRouter | `openrouter.ai` |
| Moonshot | `api.moonshot.ai` |
| MiniMax | `api.minimax.io` |
| Z.ai | `api.z.ai` |
| SambaNova | `api.sambanova.ai` |
| Qwen / DashScope | `dashscope.aliyuncs.com` |
| ByteDance ModelArk | `ark.ap-southeast.bytepluses.com` |
| Baidu Ernie | `qianfan.baidubce.com` |
| Ant Ling | `api.ant-ling.com` |
| OrcaRouter | `api.orcarouter.ai` |
| Nebius | `api.tokenfactory.nebius.com` |
| AWS Bedrock | `bedrock-mantle.us-east-1.api.aws`, `bedrock-runtime.us-east-1.amazonaws.com` |
| Azure OpenAI | The endpoint and deployment you configure |

Downloading a model from Hugging Face contacts `huggingface.co` only during the
download. Running the downloaded model is local.

## What is not collected

- No analytics or ad SDK in the desktop app.
- No crash reporting by default.
- No account, login, or device identifier required to use the app.
- Debug dumps only when you set `UNDISCLOSED_DEBUG=1`.
- The marketing site's Google Analytics is separate from the app, is off until
  you allow it, and never receives code, prompts or keys.

## Check it yourself

With the agent running, list established connections and match the hosts above.

macOS:

```bash
lsof -nP -iTCP -sTCP:ESTABLISHED | grep -Ei 'undisclosed|electron|python'
```

Linux:

```bash
ss -tpn | grep -Ei 'undisclosed|electron|python'
```

To see every host the app tries to reach, run it under a firewall that asks per
connection (Little Snitch or LuLu on macOS, OpenSnitch on Linux). An allowlist
built from the table above is the strongest audit.

For a zero-network run: pick a local model, disconnect the cloud keys, do not
add MCP servers, and block the app at the firewall. The editor, the brain and
the agent loop keep working.

## Code references

- Command classification and blocked binaries:
  `brain/app/agent/toolkit/command_policy.py`
- Approval gate:
  `brain/app/agent/toolkit/governance_toolkit.py`
- Dangerous-call regression tests:
  `brain/tests/app/agent/toolkit/test_dangerous_tool_calls.py`
- Provider hosts:
  `agent-ui/src/lib/llm.ts`
- Optional step sync (untested):
  `brain/app/utils/server/sync_step.py`
- Optional deploy toolkit (not supported yet):
  `brain/app/agent/toolkit/web_deploy_toolkit.py`

Last verified against the source tree on 2026-10-19.
