# Automate your workflow with Undisclosed triggers

Most "automation" tools make you assemble a flowchart: drag a node, wire an arrow, pick an action from a dropdown that only does the one thing the vendor imagined. Undisclosed works differently. A trigger is not a building block. It is a saved task prompt plus a way for that task to start. The agent that runs it is the same agent you talk to, with the same tools, the same files, and the same connectors.

That means the unit you automate is a full sentence in plain English, not a chain of boxes. "Read my open tasks, do the highest-priority one, and post a summary to Slack when you are done" is a valid automation, because the agent can actually do all three.

This article builds a real two-trigger workflow:

1. **A schedule trigger** that wakes up on a cron, reads your tasks, works on them, and posts to Slack when it finishes. It needs the Slack connector configured so the run can post.
2. **A Slack trigger** that fires only when the bot is tagged, writes a reply, and drops that reply into the same thread and the same conversation.

Together they close the loop: the first trigger starts work and reports it, the second lets you reply in Slack and have the agent pick the conversation back up.

---

## The mental model

Every trigger has three parts, and the dialog reflects them:

- **What runs.** The task prompt plus the agent model. This is the actual work.
- **What starts it.** Schedule, Webhook, or Slack. Scheduled triggers use a cron expression. Slack triggers use Socket Mode.
- **Where it lives.** "This workspace" ties the trigger to the folder, so it survives deleting the conversation you created it from. "This conversation" ties it to one chat while that chat is open.

Everything else in the dialog (rate limits, single execution, failure policy) is guardrails around those three.

One thing to internalize before you start: **the brain is launched by the desktop app.** Triggers run without you watching the chat panel, but if you quit the app, the brain stops and so do your triggers. "Headless" here means the panel is closed, not that the app is off.

---

## Prerequisites

- A workspace folder open in the editor. Triggers attach to a workspace, and the dialog blocks you if none is open.
- A model provider configured (your own key, or a local runtime).
- A task source the agent can read. Anything with a toolkit works: Asana, Linear, or Notion over MCP, GitHub issues via the GitHub connector, or even a `TODO.md` in the repo. This article assumes a task board reachable through a connector.
- A Slack app you control, with two tokens and a secret. See the next section.

---

## Step 1: Configure the Slack connector (the toolkit)

A trigger run only gets Slack tools if Slack is connected. The agent does not shell out to `curl`; it calls a proper `send_slack_message` tool. For that tool to exist, two things must both be true at run time: Slack credentials are set, and the connectors step of the toolkit builder is enabled. Connecting Slack in the app does both.

Open the **Connectors** screen (the same panel where you add MCP servers) and connect Slack with:

- **Bot User OAuth Token** (`xoxb-...`) - this is what the agent uses to post and read.
- **App-Level Token** (`xapp-...`) - required for Socket Mode, the outbound connection the brain opens to receive events. No public URL, no tunneling, so it works on localhost.
- **Signing Secret** - used to verify inbound requests.

Under the hood, these are written as `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, and `SLACK_SIGNING_SECRET`, and `slack_toolkit` is attached to single-agent runs only when a bot or user token is present. Unconnected, Slack contributes nothing and the agent will complain that it has no Slack tools.

Grant the bot token the scopes it needs: `chat:write` to post, plus `files:write` if you want it to upload files, and the read scopes for the channels it watches.

---

## Step 2: Trigger 1, "Work my tasks" (Schedule)

This is the worker. It runs on a clock, reads the board, does one unit of work, and reports.

Open the **Triggers** panel and click **Add Trigger**. Fill it in like this:

- **Name**: `Work my tasks`
- **Attach to**: `This workspace`
- **Trigger type**: `Schedule`
- **Cron expression**: how often to run. Format is `minute hour day month weekday`. `0 9 * * 1-5` is 9:00 on weekdays. `0 */2 * * *` is every two hours. A picker is there if you would rather not type cron.
- **Agent model**: pick the provider you want doing the work.
- **Listener type**: `Workforce` for a normal single-agent run.
- **Task prompt**: the important part. Be specific about the source, the choice, and the finish line. For example:

  > Read my open tasks from the board. Pick the highest-priority unblocked one. Do the work, and when you are finished post a short summary to the Slack channel we use for updates: what changed, what is left, and anything you need from me. Use send_slack_message to post it.

- **Execution settings**: set **Max Per Hour** and **Max Per Day** so a tight cron cannot pile up runs on you.

Save it and activate.

The phrase that makes this work is the last instruction. Because the run has the Slack toolkit (Step 1), it can post the summary itself. You do not have to wire a "then post to Slack" box; you just ask for it in the prompt.

Two prompt-writing notes that save pain:

- **Name the destination.** If you care which channel gets the update, say so ("the `#eng-updates` channel"). The agent can resolve a channel name to an ID with its Slack tools, but a clear target beats a guess.
- **Separate thinking from reporting.** Ask the agent to do the work first, then post once at the end. Otherwise you get a play-by-play in Slack.

---

## Step 3: Trigger 2, "Reply to mentions" (Slack, only when tagged)

This is the listener. It fires only when someone tags the bot, then replies in the same thread.

Click **Add Trigger** again and fill in:

- **Name**: `Reply to mentions`
- **Attach to**: `This workspace`
- **Trigger type**: `Slack`. You will see the **Socket Mode** badge, which confirms there is no URL to host.
- **Credentials**: Bot Token and Signing Secret.
- **Event Types**: select **`app_mention`** only. This is the switch that means "only when the bot was tagged." Leave the general `message` event out, or every message in the channel would fire a run.
- **Channel ID**: optionally narrow to a single channel. Leave it empty to watch every channel the bot is in.
- **Ignore Bot Messages**: on. This stops the bot from triggering itself or other bots.
- **Agent model** and **Listener type**: same as trigger 1.
- **Task prompt**: tell it to read the mention and answer in place. For example:

  > A teammate tagged you in Slack. Read the message and the thread, do what they are asking, then reply in the same thread with send_slack_message. Keep the answer concise and, unless the task needs it, do not open a new top-level message.

Save it. One behavior to expect: Slack triggers that require authentication show **Pending Verification** until they have seen one real event. Tag the bot once in Slack, that event lands, and the trigger flips to active.

---

## How the two triggers stay in one conversation

This is the part that makes the workflow feel continuous instead of like two strangers talking.

**Slack side (the reply lands in the right thread).** When the reply trigger fires, the agent's context includes the Slack event's channel, message timestamp, and thread timestamp, plus an explicit **Reply target** line that tells it to post with `send_slack_message(channel_id=..., thread_ts=...)`. Passing `thread_ts` is what makes the reply a threaded answer rather than a brand-new top-level message.

**App side (the reply reopens the right conversation).** When any run posts to Slack, `send_slack_message` records a link from that thread to the conversation the run belongs to. When your reply arrives, the brain looks that link up and runs your reply *in the conversation that opened the thread*, instead of starting a fresh chat. So the whole back-and-forth stays in one place you can scroll.

Put together: trigger 1 works a task and opens a Slack thread. You reply in that thread. Trigger 2 fires on the mention, runs in the original conversation, and answers in the same thread. Repeat.

---

## Seeing what happened

Open a trigger's **Executions** list to see every run: status (`running`, `completed`, `failed`), start time, duration, tokens used, and the tools it called. The list is live, so an open trigger panel reflects a run that is in progress without you owning it. When a run fails, the error message and the failure count are right there, which is the fastest way to tell a bad prompt from a bad connector.

---

## Honest limits

- **Prompts are not contracts.** The threaded reply depends on the agent obeying the instruction to pass `thread_ts`. It is reliable, but it is prompt-level, not enforced server-side. If you need a hard guarantee, that is a larger change to have the brain post the run's final answer into the thread itself.
- **Tool calling is required.** The Slack reply works because the model selects a tool. Some bring-your-own-key models do not support tool calls well, and those will not post. Pick a model with solid tool use for Slack triggers.
- **Mentions, not passive threads.** Trigger 2 listens for `app_mention`. A plain threaded reply that does not tag the bot will not reach it, by design. If you want untagged replies to work, the Slack app needs the `message.channels` or `channels:history` subscription, which also means every channel message becomes an event, so scope it with a message filter or a specific channel.
- **The app, not the cloud, runs it.** Quit the desktop app and the brain stops, so Socket Mode and the scheduler stop with it. Always-on operation is a separate step (running the brain as a background service).
- **Rate limits protect you.** Set Max Per Hour and Max Per Day. A trigger that fires on a busy channel can pile up runs faster than you expect.

---

## Troubleshooting

- **The run says it has no Slack tools.** The Slack connector is not configured, or the bot token is missing. Reconnect Slack in the Connectors screen and re-run.
- **The reply posts as a new top-level message.** The agent did not pass `thread_ts`. Tighten the prompt to say "reply in the thread, do not post a new top-level message."
- **Trigger 2 never fires.** Check three things: the event type is `app_mention`, the person actually tagged the bot, and the bot is a member of the channel.
- **A schedule never runs.** Confirm the trigger is active and the cron is valid (`minute hour day month weekday`), and that the desktop app is open.
- **Too many runs.** Lower Max Per Hour, narrow the Slack trigger to one channel, or turn on Ignore Bot Messages.

---

## The two triggers at a glance

| | Work my tasks | Reply to mentions |
| --- | --- | --- |
| Type | Schedule | Slack |
| Starts when | Cron fires | Someone tags the bot |
| Reads | Your task board | The Slack mention and thread |
| Ends by | Posting a summary to Slack | Replying in the same thread |
| Needs | Slack connector configured | `app_mention` event, bot in channel |
| Continuity | Opens a thread and records the link | Reuses the link and replies in-thread |

Set both up once and you have a loop that does the work, tells you it is done, and answers when you talk back, all inside the same conversation.
