# MUXE

A local AI coding partner that runs entirely on your own machine.
No cloud, no API keys, no accounts — just a small model on your CPU.

Think Claude Code, but offline and yours.

---

## Install (Windows)

The password is set by whoever owns the repo — ask them for it.

Open **PowerShell** and paste one line:

```powershell
irm https://raw.githubusercontent.com/unknowncoder321/muxe-ai/main/install.ps1 | iex
```

It will ask for the password, then set everything up. Takes a few minutes —
most of that is downloading the model.

When it finishes, **open a new terminal** and type:

```
muxe
```

---

## What the installer does

1. Asks for the password (checked against a SHA-256 hash — the password itself is never stored)
2. Finds Python 3, or installs it automatically with `winget`
3. Downloads the MUXE source
4. Creates a private virtualenv and installs:
   `pyyaml`, `rich`, `psutil`, `llama-cpp-python`
5. Detects your free RAM and downloads the biggest model you can actually run
6. Creates a portable `muxe` launcher and adds it to your PATH

Re-running the installer is safe. It upgrades in place and **keeps your models**,
so it won't re-download gigabytes.

---

## Which model do I get?

Picked automatically from your free RAM:

| Free RAM | Model | Size |
| --- | --- | --- |
| 3.4 GB + | Qwen3-4B-Instruct | 2.33 GB |
| 1.9 GB + | Qwen2.5-Coder-1.5B | 1.04 GB |
| below | Qwen2.5-0.5B | 0.46 GB |

Bigger = smarter but slower. The 4B is the sweet spot on a 6 GB machine.

A 7B model needs 3.4–4.5 GB and will **not** fit in 6 GB of total RAM —
it would page off the SSD and crawl. Don't bother.

---

## Requirements

- Windows 10 or 11
- ~5 GB free disk space
- 4 GB RAM minimum (6 GB+ recommended)
- Internet connection for the first install only

After that it runs fully offline.

---

## Using it

```
muxe                        interactive chat
muxe "fix my typecheck"     one-shot, prints the answer and exits
muxe --help                 options
```

Inside MUXE:

| command | effect |
| --- | --- |
| `/help` | all commands |
| `/new` `/list` `/load` | chat management |
| `/copy` | copy the last code block to the clipboard |
| `/online` `/offline` | toggle web search on and off |
| `/web <query>` | search the web and answer from the results |
| `/stats` `/config` | settings and last-run info |
| `/quit` | save and exit |

**It can create files and folders** — just like Claude Code. Ask it to build
something and it will write the files next to you:

```
> create a script called wordcount.py that counts words in a file
```

Anything else (opening apps, controlling the system) is deliberately disabled.

---

## Changing the password

Generate a new hash:

```powershell
[BitConverter]::ToString([Security.Cryptography.SHA256]::Create()
  .ComputeHash([Text.Encoding]::UTF8.GetBytes('your-new-password'))
).Replace('-','').ToLower()
```

Paste the result into `$PWHASH` at the top of `install.ps1` and push.

⚠️ **This is a speed bump, not real security.** Anyone who can read
`install.ps1` can read the hash, and can just edit the file to bypass it
entirely. It keeps out casual snooping — nothing more.

---

## Repo layout

```
muxe/
├── install.ps1        the one-line installer
├── README.md
└── gully/             the Python package
    ├── muxe.py        terminal UI + chat loop
    ├── engine.py      model backends
    ├── config.py      config loading
    ├── control.py     file/folder creation
    ├── store.py       saved conversations
    ├── websearch.py   DuckDuckGo search
    ├── persona.txt    system prompt
    └── config.yaml    model + generation settings
```

## Updating

Push a change to `main`, then on any machine re-run the install one-liner.
It replaces `gully/` and keeps your models and your saved chats.

## Uninstalling

```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\MUXE"
```

Then remove `%LOCALAPPDATA%\MUXE` from your PATH in
*Edit environment variables for your account*.
