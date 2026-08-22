# DSH Workbench Deployment

One-command launch of the edu-agent student workbench: a `dsh` web-profile
instance with three edu plugins mounted, the `student` preset pre-provisioned,
and browser sessions transparently bound to edu-agent accounts.

```bash
./run.sh                # port 3090, default env
./run.sh --port 3091    # override port
```

## Architecture

```
+------------------+        +---------------------------+
| Student Browser   |        | dsh host (web profile)    |
|                  | HTTP   |  port 3090                |
|  dsh web UI      +------->|  plugins:                 |
|  (login: student |        |   edu-auth           <----+-- patches/*.cordis.yml
|   username/pw)   |        |   edu-session-owner  <----+-- (per-run, rewritten
|                  |        |   edu-tools          <----+    absolute paths)   |
+------------------+        |  preset: student           |
        |  browser session  +-------------+-------------+
        |  cookie -> edu JWT              | EDU_TOKEN / EDU_BASE_URL
        v                                v
+--------------------------------------------------+
| edu-agent FastAPI (:8000)  +  PostgreSQL          |
|   /auth/login, /api/mistakes, /api/curriculum,   |
|   /api/session.*  (JWT-protected)                |
+--------------------------------------------------+
```

- **edu-auth**: browser login form (`POST /workbench` with username/password)
  exchanges credentials for an edu JWT and injects it as `edu_token` into the
  session env.
- **edu-session-owner**: binds every dsh session to the logged-in student.
- **edu-tools**: teaching tools (`query_mistakes`, `get_curriculum`,
  `submit_answer`) calling the FastAPI backend with `EDU_TOKEN`.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DSH_HOME_DIR` | `$PWD/.dsh-home` | Scratch DSH_HOME; receives patches + `.agent-presets/student` |
| `PORT` | `3090` | Web UI port |
| `EDU_BACKEND` | `http://127.0.0.1:8000` | edu-agent FastAPI base URL |
| `EDU_JWT_SECRET` | *(empty)* | Must match backend's JWT secret in production; empty uses the plugin default (= backend dev default) |
| `EDU_TOKEN` | *(empty)* | Student JWT used by edu-tools backend calls |
| `NODE_BIN` | nvm node v24.12.0 | Node binary (must be >= 24) |
| `DSH_REPO` | `~/workspace/deepseek-harness` | dsh checkout to launch from |

Flags: `--port`, `--dsh-home`, `--edu-backend`, `--jwt-secret`.

## Quick start

```bash
# 1) Start the backend first (it must be up before students log in)
cd ~/workspace/edu-agent && ./scripts/dev.sh   # FastAPI + PostgreSQL

# 2) Launch the workbench
cd ~/workspace/edu-agent/dsh-workbench
DSH_HOME_DIR=/tmp/edu-home EDU_TOKEN="$TOKEN" ./run.sh
```

Open `http://localhost:3090`, log in with a student account
(e.g. `t12student` / `Passw0rd!`).

## Known pitfalls

- **Node >= 24 required.** The system Node 22 dies with
  `ERR_REQUIRE_CYCLE_MODULE` under the tsx ESM source launch; run.sh pins a
  v24 `NODE_BIN` for exactly this reason.
- **Presets load only from `$DSH_HOME/.agent-presets`.** A preset cannot be
  injected via `--patch`; run.sh therefore copies + rewrites the student
  preset into the scratch DSH_HOME before launch.
- **Workspace must be added once in the UI.** A fresh `DSH_HOME_DIR` has no
  workspaces; on first login click "add workspace" manually — after that the
  student preset appears in the composer.
- **Production must set `EDU_JWT_SECRET`** to the same value as the backend;
  with the empty default any deployment sharing the default secret can mint
  tokens for the other.
