# PRD — Pressure Harness

**Local coding agent harness สำหรับ ChatGPT**

| | |
|---|---|
| เวอร์ชันเอกสาร | 0.1 (draft) |
| สถานะ | รออนุมัติ — ยังไม่เริ่มเขียนโค้ด |
| วันที่ | 2026-08-24 |
| ชื่อโครงการ | **Pressure Harness** (ยืนยันแล้ว) |
| tagline | ควบคุม AI ให้เขียนโค้ดบนเครื่องคุณได้ โดยที่คุณยังถือบังเหียน<br>*Local coding agent harness for ChatGPT — full reach, on your leash* |
| ขอบเขตเอกสารนี้ | v1 = Windows + scope B (dev tools + browser) |

---

## 1. บทสรุป

Pressure Harness คือโปรแกรมที่ติดตั้งบนเครื่องผู้ใช้ ทำหน้าที่เป็น **MCP server** ที่เปิดให้ ChatGPT
เรียกใช้ความสามารถบนเครื่องได้ — อ่าน/แก้โค้ด, รัน test, คุม git, สั่ง dev server,
และคุม Chrome ผ่าน CDP เพื่อตรวจผลงานที่เพิ่งแก้ไป

ผู้ใช้ยังคงพิมพ์คุยใน ChatGPT ตามปกติ (เว็บ หรือ desktop app) — Pressure Harness **ไม่มีหน้าจอแชท**
มีเพียงหน้าคอนโซลสำหรับควบคุมสิทธิ์ ดูกิจกรรม และย้อนการเปลี่ยนแปลง

ผลลัพธ์คือได้ประสบการณ์ใกล้เคียง Codex CLI / Claude Code แต่ใช้ **โควตาแชทของบัญชี ChatGPT
ที่ผู้ใช้จ่ายรายเดือนอยู่แล้ว** ผ่านฟีเจอร์ custom connector ที่ OpenAI เปิดให้ใช้อย่างเป็นทางการ

---

## 2. ที่มาและปัญหา

ChatGPT รันบน cloud จึงไม่มี "มือ" — อ่านไฟล์ในเครื่องไม่ได้ รันคำสั่งไม่ได้
ผู้ใช้ต้อง copy-paste โค้ดไปมา และ copy error กลับไปถามซ้ำ

เครื่องมือที่แก้ปัญหานี้ (Codex CLI, Claude Code) คิดค่าใช้จ่ายแยกจากโควตาแชท
ผู้ใช้ที่จ่ายค่าสมาชิก ChatGPT อยู่แล้วจึงต้องจ่ายซ้ำซ้อน

ขณะเดียวกัน OpenAI เปิดฟีเจอร์ **Developer mode + custom MCP connector** ให้ผู้ใช้
ลงทะเบียน MCP server ของตัวเองได้ ซึ่งเป็นช่องทางที่ตั้งใจออกแบบมาให้ทำสิ่งนี้พอดี

### 2.1 หลักฐานว่าตลาดต้องการ

มีผู้ใช้ประกอบเครื่องมือลักษณะนี้ขึ้นเองและแชร์ในวงกว้าง (ดู §18 การประเมินของอ้างอิง)
แต่เท่าที่ตรวจสอบ ของที่มีอยู่ยัง **ขาดระบบสิทธิ์และการขออนุมัติโดยสิ้นเชิง**
ซึ่งเป็นช่องว่างที่ Pressure Harness จะเข้าไปแทนที่

---

## 3. เป้าหมาย / ไม่ใช่เป้าหมาย

### 3.1 เป้าหมาย (v1)

- G1 — ผู้ใช้สั่งงานเขียน/แก้/ตรวจโค้ดจากแชท ChatGPT ได้จริงบนเครื่อง Windows ของตัวเอง
- G2 — agent ตรวจผลงานตัวเองได้ผ่าน browser (CDP) ไม่ใช่แค่เดาว่าโค้ดน่าจะถูก
- G3 — **ทุกการกระทำต้องมองเห็นได้ หยุดได้ และย้อนได้** โดยไม่ต้องเชื่อว่า AI จะทำตัวดี
- G4 — ค่าเริ่มต้นปลอดภัยพอที่จะแจกให้คนอื่นติดตั้งใช้ได้
- G5 — ประหยัดโควตา: ควบคุมปริมาณข้อมูลที่ส่งกลับเข้าบทสนทนา
- G6 — โครงสร้างพร้อมพอร์ตไป macOS / Linux โดยไม่ต้องรื้อ core

### 3.2 ไม่ใช่เป้าหมาย

- N1 — **ไม่สร้าง UI แชทของตัวเอง** (จะต้องใช้ API key ซึ่งขัดกับเป้าหมายทั้งหมด)
- N2 — **ไม่แตะ token / cookie / session ของบัญชี ChatGPT** และไม่เรียก backend API ที่ไม่เปิดสาธารณะ
- N3 — ไม่ทำ desktop automation (Office, UI Automation, audio, screen record) ใน v1 → Phase 2
- N4 — ไม่ทำ GitHub integration ใน v1 (git CLI ครอบคลุมงานจริงไปแล้ว) → Phase 2
- N5 — ไม่รองรับผู้ใช้หลายคน / ไม่ใช่บริการ multi-tenant — 1 ติดตั้ง = 1 เครื่อง = 1 เจ้าของ
- N6 — ไม่มี telemetry ไม่ส่งข้อมูลไปที่ไหนนอกจากปลายทางที่ผู้ใช้ตั้งเอง

---

## 4. จุดยืนด้านกฎและ ToS

ข้อนี้เขียนไว้ชัดเพราะเป็นเส้นที่ห้ามข้าม และเพราะเราจะแจกให้คนอื่นใช้

| ทำ ✅ | ไม่ทำ ❌ |
|---|---|
| ใช้ฟีเจอร์ custom MCP connector ตามที่ OpenAI เปิดให้ | ดึง session token / cookie จาก chatgpt.com |
| ให้ ChatGPT เป็น client เรียก tool ของเรา | ยิง backend endpoint ที่ไม่ได้เปิดเป็น public API |
| ติดป้าย MCP annotation ตามจริง (`readOnlyHint`, `destructiveHint`) | ติดป้าย tool เขียนไฟล์ว่าเป็น read-only เพื่อหลบการบล็อกฝั่ง client |
| เคารพกลไกความปลอดภัยของแพลตฟอร์ม | ออกแบบเพื่อหลบเลี่ยงข้อจำกัดของแพลตฟอร์ม |

การใช้โควตาแชทแทนโควตา Codex **ไม่ใช่การเลี่ยงกฎ** — เพราะทุก tool call คือข้อความจริง
ในบทสนทนาจริง ที่ถูกนับตามแพ็กเกจจริง เราไม่ได้ทำอะไรให้มันไม่ถูกนับ

---

## 5. ผู้ใช้เป้าหมาย

- **P1 — นักพัฒนาที่จ่ายค่า ChatGPT อยู่แล้ว** ต้องการ agent ช่วยเขียนโค้ดโดยไม่จ่ายเพิ่ม (ผู้ใช้หลัก)
- **P2 — ผู้รับแจกโปรแกรม** ไม่ได้เขียน Pressure Harness เอง ตั้งค่าไม่เป็น ต้องการติดตั้งแล้วใช้ได้ใน 10 นาที

### 5.1 User stories

- US1 — ในฐานะ P1 ฉันเลือกโฟลเดอร์โปรเจกต์และกำหนดสิทธิ์ให้มันได้ก่อนเริ่มใช้งาน
- US2 — ฉันบอก ChatGPT ว่า "แก้บั๊กหน้า checkout" แล้วมันอ่านโค้ด แก้ รัน test และรายงานผลกลับมา
- US3 — ฉันให้มันเปิดหน้าเว็บที่เพิ่งแก้ใน Chrome แล้วส่ง screenshot + console error กลับมาให้ดู
- US4 — เมื่อ AI จะรันคำสั่งที่ไม่อยู่ใน allowlist ฉันเห็นหน้าต่างขออนุมัติที่แสดง **คำสั่งจริง** และกดปฏิเสธได้
- US5 — ฉันย้อนดูได้ว่าวันนี้ AI ทำอะไรไปบ้าง และย้อนการแก้ไฟล์กลับได้เป็นชุด
- US6 — ในฐานะ P2 ฉันติดตั้ง เปิด wizard ต่อ ChatGPT ตามขั้นตอน แล้วใช้งานได้โดยไม่ต้องแก้ไฟล์ config

---

## 6. สถาปัตยกรรม

```
 ┌──────────────────────────────────────────┐
 │  ChatGPT (cloud)                         │   ผู้ใช้พิมพ์ที่นี่
 │  web / desktop app / mobile              │   ทำหน้าที่เป็น "สมอง"
 └───────────────┬──────────────────────────┘
                 │
      ┌──────────┴──────────┐
      │                     │
 (A) HTTPS + tunnel    (B) stdio
  ChatGPT web           ChatGPT desktop /
  (ทุกอุปกรณ์)          Codex CLI / IDE ext
      │                     │
      └──────────┬──────────┘
                 ▼
 ┌──────────────────────────────────────────┐
 │  Pressure Harness (เครื่องผู้ใช้)         │
 │                                          │
 │  transport  →  policy engine  →  tools   │
 │                     ↓                    │
 │              approval queue              │
 │                     ↓                    │
 │        native approval dialog  ──────────┼──▶ ผู้ใช้กดอนุมัติที่นี่
 │                                          │     (นอกแชท — ดู §10)
 │  audit log (hash-chained) · journal/undo │
 │  console UI (pywebview) · tray           │
 └───────────────┬──────────────────────────┘
                 ▼
   ไฟล์ · git · child process · Chrome (CDP)
```

### 6.1 หลักการออกแบบ 5 ข้อ

1. **Policy อยู่ระหว่าง transport กับ tool เสมอ** — ไม่มี tool ไหนถูกเรียกโดยไม่ผ่านตัวตัดสิน
2. **AI แก้กฎที่คุมตัวเองไม่ได้** — ไม่มี tool ใดเข้าถึง config ของ Pressure Harness
3. **อนุมัติที่ payload ไม่ใช่ที่คำบรรยาย** — ดู §10.1
4. **Undo สำคัญกว่าการห้าม** — กฎมีรูรั่วเสมอ ตาข่ายต้องมี
5. **core ไม่รู้จัก OS** — ดู §14

---

## 7. ช่องทางเชื่อมต่อ (Transport)

| | (A) Remote HTTPS + tunnel | (B) stdio |
|---|---|---|
| ใครเรียก tool | เซิร์ฟเวอร์ OpenAI ยิงเข้า URL ของเรา | แอปบนเครื่อง spawn process เอง |
| ตั้งค่าที่ | ChatGPT Settings → Apps → Developer mode → Add custom connector | config ของ ChatGPT desktop / Codex CLI |
| ใช้จากอุปกรณ์อื่นได้ | **ได้** (ผูกกับบัญชี) | ไม่ได้ |
| ต้องมี tunnel | ต้องมี (cloudflared / ngrok / tailscale funnel — outbound-only) | ไม่ต้อง |
| ต้องมี auth | **บังคับ** (§10.6) | ไม่ต้อง (localhost process) |
| latency | สูงกว่า | ต่ำสุด |

**v1 รองรับทั้งสอง** โดยใช้ tool layer ชุดเดียวกัน ต่างกันแค่ entrypoint
(ลงมือแล้ว: `ph serve` = stdio, `ph serve --http` = Streamable HTTP)

- โปรโตคอลที่รองรับฝั่ง HTTP: **Streamable HTTP** (หลัก) และ SSE (สำรอง)
- Pressure Harness เป็นผู้จัดการ tunnel เอง (start/stop/สถานะ อยู่ในแอป) ไม่ให้สคริปต์ภายนอกคุม
  — ลงมือแล้วใน M7 (`ph serve --http --tunnel`) และเหตุผลที่ต้องทำเองชัดขึ้นตอนเขียน:
  **OAuth issuer ต้องเป็น URL ที่ client เข้าถึงได้จริง** ถ้าแอปไม่รู้ที่อยู่ของตัวเอง
  metadata จะประกาศ URL ที่เข้าไม่ถึง ซึ่ง debug จากฝั่ง client ยากมาก
- ค่าเริ่มต้น bind `127.0.0.1` เท่านั้น ไม่ bind `0.0.0.0` ไม่ว่ากรณีใด

---

## 8. Tool catalog (v1)

### 8.1 หลักการออกแบบ catalog

- **จำนวน tool น้อยแต่มี `op`** — schema ของทุก tool ถูกส่งเข้า context **ทุกครั้ง** ที่คุยกัน
  60 tool ย่อยกินโควตาฟรีๆ ทุกข้อความ → รวบเป็น ~14 tool ที่มีพารามิเตอร์ `op`
- **registry สร้างตอน runtime** ตาม capability ที่ adapter ของ OS นั้นประกาศ (§14.3)
- **ทุก tool ประกาศ MCP annotation ตามจริง** (`readOnlyHint` / `destructiveHint` / `idempotentHint`)
- **ทุก tool รับ `workspace` (optional)** — ถ้าไม่ระบุใช้ค่า active ของ session นั้น (§9.3)

> **สถานะจริง:** ลงไปแล้ว 14 tool — `workspace`, `read_file`, `search`,
> `write_file`, `apply_patch`, `git`, `project`, `shell`, `process`, `browser`,
> `web_fetch`, `codex_run`, `notify`, `system` — ครบตามที่วางไว้ใน §8.2

### 8.2 รายการ

| # | tool | ops | tier | หมายเหตุ |
|---|---|---|---|---|
| 1 | `workspace` | list, use, tree, info | T0 | `info` คืน branch, ไฟล์ค้าง, ภาษา/แพ็กเกจที่ตรวจพบ |
| 2 | `read_file` | — | T0 | รองรับ offset/limit, เพดาน bytes, ตรวจ binary |
| 3 | `search` | text, files | T0 | regex + glob, คืน `path:line` + snippet, เพดานผลลัพธ์; **ข้ามไฟล์ลับและ `node_modules`/`.git` เสมอ** — ไม่งั้น search จะกลายเป็นประตูหลังไปอ่านสิ่งที่ `read_file` ปฏิเสธ |
| 4 | `write_file` | — | T1 | ค่าเริ่มต้น `create_only=true`; เขียนทับต้องระบุชัด + ลง journal |
| 5 | `apply_patch` | — | T1 | unified diff หลายไฟล์, atomic, `dry_run`, ลง journal |
| 6 | `git` | status, diff, log, show, branch, add, commit, stash, checkpoint, undo | T0/T1 | `push` = T4; `reset --hard`/ลบ branch = T5 |
| 7 | `project` | dev, test, lint, typecheck, build | T2 | รัน script ที่ผู้ใช้ map ไว้; แสดงคำสั่งจริงที่จะรัน |
| 7b | `project` | install | **T4** | ปรับจาก T2 ตอน M1 — การติดตั้งดาวน์โหลดโค้ดแล้วรัน install script ทันที ถือเป็น egress + exec |
| 8 | `process` | list, logs, stop, start | T1/T2 | log เขียนลงไฟล์ ไม่ใช่ pipe (pipe ที่ไม่มีใครอ่านจะ deadlock) ส่งกลับเฉพาะ tail; **stop ฆ่าทั้งต้นไม้** — ฆ่าแค่ตัวแม่จะเหลือ dev server ครองพอร์ตอยู่ ซึ่งดูเหมือนบั๊กของเราเอง |
| 9 | `shell` | exec | T3 | ผ่านตัวสแกน §10.4 เสมอ |
| 10 | `browser` | launch, navigate, snapshot, click, type, eval, console, network, screenshot | T2/T3 | CDP; `eval` = T3 |
| 11 | `web_fetch` | — | T4 | domain allowlist, บล็อก IP วงใน §10.5 |
| 12 | `codex_run` | — | T3 | มอบงานต่อให้ Codex CLI / Claude Code แบบ headless บนเครื่อง |
| 13 | `system` | info, health | T0 | CPU/RAM/disk/สถานะ backend |
| 14 | `notify` | — | T0 | ให้ agent เรียกความสนใจผู้ใช้ที่หน้าเครื่องได้ |

> **เพิ่มตอน M6:** `browser` มี 9 op (launch/navigate/snapshot/click/type/eval/console/network/screenshot)
> และ `web_fetch` แยกออกมา — รวมเป็น **13 tool** ที่ประกาศออกไป
>
> - `browser` จะถูกประกาศ **ก็ต่อเมื่อหา Chrome/Chromium เจอจริงบนเครื่องนั้น** (ตรวจตอน startup)
> - `snapshot` คืน **ข้อความ + รายการ element ที่กดได้** ไม่ใช่ HTML ดิบ เพราะ HTML ส่วนใหญ่
>   เป็น attribute กับ closing tag ซึ่งกิน budget มากแต่บอกอะไรน้อย
> - `screenshot` **บันทึกไฟล์แล้วคืน path** ไม่ส่งรูปเข้าแชท เพราะ OQ-2 ยังไม่มีคำตอบ
>   (บันทึกไฟล์ใช้ได้แน่ ส่งรูปอาจใช้ไม่ได้)
> - `web_fetch` **ปฏิเสธ address ในวงในทั้งหมด** รวม loopback — ของในเครื่องให้ใช้ browser
>   ซึ่งเห็นได้ชัดเจนกว่า และตรวจ IP ใหม่ทุกครั้งที่ redirect เพราะ redirect คือ address ใหม่

### 8.2b คำสั่ง container กับ allowlist ที่แนะนำ

`docker` ไม่ได้ถูกลดระดับให้อัตโนมัติ — เหมือน `git status` ที่ต้องใส่ allowlist เอง
เพราะการลด tier เป็นการตัดสินใจของผู้ใช้ ไม่ใช่ของตัวสแกน ชุดที่แนะนำสำหรับงานประจำวัน:

```toml
allow_commands = [
  "docker ps", "docker images", "docker inspect", "docker logs",
  "docker compose ps", "docker compose logs", "docker compose up",
  "docker compose exec",          # ครอบ migration ที่รันในคอนเทนเนอร์
]
```

`docker start/stop/restart`, `docker rm`, `docker compose down` (ไม่มี `-v`) → **ถาม**
`docker pull/push/build` → **ถาม (T4)** เพราะ build รันอะไรก็ได้ตามที่ Dockerfile บอก
`docker -H tcp://...` / `--context` → **T4** เพราะกำลังสั่งงานเครื่องอื่น

> **ข้อจำกัดที่ต้องรู้: migration ย้อนกลับไม่ได้**
> journal เก็บ pre-image ของไฟล์เท่านั้น ไม่ได้ dump database
> `docker compose exec api npm run migrate` ที่ผิดพลาด **undo ไม่ได้ด้วยเครื่องมือนี้**
> ทางที่ถูกคือ backup ก่อน migrate หรือใช้ migration ที่มี `down` ของตัวเอง

### 8.3 หมายเหตุที่สำคัญต่อความปลอดภัย

- **`project.*` ปลอดภัยแค่เท่าที่ `package.json` ปลอดภัย** — ใครก็แก้ script ให้ทำอะไรก็ได้
  ตอนขออนุมัติจึงต้องแสดงคำสั่งที่ script นั้น resolve ออกมาจริงๆ ไม่ใช่แค่ชื่อ script
  (ลง M3 แล้ว: ผลลัพธ์ทุกครั้งขึ้นต้นด้วย `$ <คำสั่งเต็ม>` และบอกว่ามันมาจากไหน —
  จาก config ของ workspace หรือจาก `package.json`)
- **git ถูกเรียกแบบ argv ไม่ผ่าน shell** — ชื่อ branch หรือชื่อไฟล์จึงกลายเป็นคำสั่งที่สองไม่ได้
  และ **ไม่มี `--amend`** เพราะการแก้ commit ที่อาจ push ไปแล้วคือการรื้อประวัติ; commit ผิดให้ commit ใหม่
- **`browser.eval` และ `codex_run` คือช่องหนีทุกกฎ** — ต้องนับเป็น T3 เสมอ ห้ามใส่ allowlist อัตโนมัติ
  (ลงแล้ว) `codex_run` เป็นกรณีที่ชัดที่สุด: delegate คือ agent ที่มีสิทธิ์ของตัวเอง
  **สิ่งที่มันทำไม่ผ่าน policy engine ของเราเลยสักอย่าง** หน้าต่างขออนุมัติจึงต้องแสดง
  task ทั้งก้อนกับคำสั่งเต็ม เพราะนั่นคือจุดสุดท้ายที่ฝั่งเราตัดสินใจอะไรได้
- **task ของ delegate ถูกวางเป็น argv ตัวเดียว ไม่ผ่าน shell** — ไม่งั้นทุกเครื่องหมายคำพูด
  ใน task จะกลายเป็นวิธีเปลี่ยนคำสั่ง
- **`browser.snapshot` / `web_fetch` คืนเนื้อหาจากภายนอก** — ต้องห่อด้วยเครื่องหมายบอกที่มา (§10.5)

---

## 9. การจัดการโปรเจกต์ (Workspace)

### 9.1 แยก "อนุญาต" ออกจาก "เลือก"

| | ใครทำ | ที่ไหน | ความถี่ |
|---|---|---|---|
| **อนุญาตโฟลเดอร์** (register) | ผู้ใช้เท่านั้น | UI / CLI บนเครื่อง | ครั้งเดียวต่อโปรเจกต์ |
| **เลือกโปรเจกต์ที่จะทำงาน** | ChatGPT | ในแชท (`workspace.use`) | ทุกบทสนทนา |

AI **เพิ่ม workspace ใหม่เองไม่ได้** ขอ path นอกรายการ = ถูกปฏิเสธที่ชั้นโค้ด
พร้อมข้อความบอกว่ามีโปรเจกต์อะไรให้ใช้บ้าง

### 9.2 การเพิ่มโปรเจกต์

1. UI → ปุ่มเพิ่มโปรเจกต์ → **native folder picker** (ไม่ใช่ช่องพิมพ์ path)
2. เด้งฟอร์มตั้ง alias + สิทธิ์ (อ่าน / เขียน / รันคำสั่ง / git push)
3. **เตือนถ้าเลือกกว้างเกินไป** — root ของไดรฟ์, `C:\Users\<user>`, `Desktop`, `Documents`
   → แสดงคำเตือนชัดเจนและต้องกดยืนยันซ้ำ
4. ทางเลือกสำหรับผู้ใช้ขั้นสูง: `ph workspace add <path> --alias <name> [--read-only]`

### 9.3 หลายบทสนทนาพร้อมกัน

active workspace ผูกกับ **session** ไม่ใช่ตัวแปร global เดียว —
มิฉะนั้นเปิด 2 แชทพร้อมกันแล้วแชทหนึ่งจะเขียนไฟล์ลงโปรเจกต์ของอีกแชทโดยไม่มีใครรู้

ถ้ามี workspace เดียวที่ลงทะเบียนไว้ ให้ใช้เป็นค่าเริ่มต้นโดยไม่ต้องเรียก `workspace.use`

---

## 10. ระบบสิทธิ์และความปลอดภัย  ← แกนหลักของผลิตภัณฑ์

### 10.1 ทำไมการอนุมัติต้องอยู่นอกแชท

การถามอนุมัติในแชทใช้เป็นกลไกความปลอดภัยไม่ได้ ด้วย 2 เหตุผล:

1. **ผู้ใช้จะอนุมัติ "คำบรรยาย" ไม่ใช่ "คำสั่งจริง"** — ข้อความในแชทถูกเขียนโดยโมเดล
   ไม่มีอะไรผูกมันกับ payload ที่ส่งมาถึงเราจริงๆ แค่โมเดลสรุปเพี้ยนตามปกติก็พังแล้ว
2. **ผู้ขอกับผู้อนุมัติอยู่ในท่อเดียวกัน** — ถ้า agent ถูก prompt injection
   เนื้อหาที่หลอกมันได้ก็ปลอมขั้นตอนอนุมัติได้ด้วย

> ต่างจาก Claude Code / Codex ตรงที่ UI ที่ถามของเขา **คือ client ตัวเดียวกับที่รัน tool**
> และแสดง payload ดิบ แต่ client ของเราคือ ChatGPT บน cloud ที่เราควบคุมไม่ได้เลย

**หลักการ: approve the payload, not the narrative**

การยืนยันของ ChatGPT เอง (confirmation setting ของ connector) ถือเป็น *ลูกระนาดชั้นแรก*
มีก็ดี แต่ห้ามพึ่งเป็นชั้นตัดสิน

### 10.2 โหมดสิทธิ์ (ตั้งแยกรายโปรเจกต์)

| โหมด | อ่าน | แก้ไฟล์ในโปรเจกต์ | รันคำสั่ง |
|---|---|---|---|
| `read-only` | ✅ | ❌ | ❌ |
| `auto-edit` **(ค่าเริ่มต้น)** | ✅ | ✅ | เฉพาะใน allowlist — นอกนั้นถาม |
| `full-access` | ✅ | ✅ | ✅ ยกเว้น T5 |

- `full-access` **ต้องมีวันหมดอายุเสมอ** (ค่าเริ่มต้น 2 ชม.) แล้วตกกลับ `auto-edit` อัตโนมัติ
  พร้อมนับถอยหลังบน Dashboard — เพราะคนเปิดตอนเร่งงานแล้วลืมปิดกันทุกคน
- **ห้ามมีโหมด "unrestricted" ถาวร** และห้ามให้ตั้งเป็นค่าเริ่มต้นตอนติดตั้ง

### 10.3 ลำดับการตัดสิน (first match wins, fail closed)

```
1. T5 HARD DENY      → ปฏิเสธถาวร ไม่มีปุ่มให้อนุมัติ
2. deny rules ของผู้ใช้
3. allow rules ของผู้ใช้ (รวมกฎที่กด "จำไว้")
4. ค่าเริ่มต้นตาม tier + โหมดของโปรเจกต์
5. ไม่เข้าข้อไหน → เข้าคิวถาม
```

**Tier**

| tier | ความหมาย | พฤติกรรมใน `auto-edit` |
|---|---|---|
| T0 | อ่านอย่างเดียว | อนุญาตอัตโนมัติ |
| T1 | เขียนในโปรเจกต์ (ลง journal) | อนุญาตอัตโนมัติ |
| T2 | รันคำสั่งใน allowlist | อนุญาตอัตโนมัติ |
| T3 | รันคำสั่งอื่น / `eval` / `codex_run` | **ถาม** |
| T4 | ส่งข้อมูลออกนอก (`git push`, `web_fetch` นอก allowlist) | **ถาม** |
| T5 | ห้ามถาวร | ปฏิเสธ |

**T5 มีอะไรบ้าง** (ปิดตายในโค้ด ไม่มีปุ่มเปิด):

> **เพิ่มหลัง v1: container runtime** (`docker`, `podman`, `nerdctl`)
> — container คือวิธี*รันคำสั่งด้วยกฎที่ต่างจาก host* ซึ่งเป็นสิ่งเดียวกับที่ policy engine
> มีไว้ตัดสิน การมองว่า `docker` เป็นโปรแกรมทึบตัวหนึ่งทำให้ `docker exec api rm -rf /`
> อ่านออกมาเป็นคำที่ไม่มีพิษภัยสองคำ

- path นอก workspace, `..` หลุดออก, symlink/junction ชี้ออกนอก (ตรวจหลัง `realpath`)
- ไฟล์ลับ: `.env*`, `~/.ssh`, `~/.aws`, `~/.config/gh`, `.git/config`, โปรไฟล์เบราว์เซอร์
- **config และ audit log ของ Pressure Harness เอง**
- คำสั่งทำลาย: `rm`, `del`, `rmdir`, `Remove-Item`, `format`, `mkfs`, `diskpart`,
  `truncate`, redirect `>` ทับไฟล์ที่มีอยู่
- ดาวน์โหลดมารันทันที: `curl … | sh`, `iwr … | iex`, `Invoke-Expression`
- `git push --force`/`--mirror`/`--delete`, `git branch -D`, `git tag -d`, `git filter-branch`
- `git reset --hard` และ `git clean -f*` — **เข้มกว่าที่ร่างไว้เดิม (ตัดสินตอน M1)**
  เดิมเขียนว่า "บน branch หลัก" แต่ตอน classify เรายังไม่รู้ว่าอยู่ branch ไหน
  (ต้องเรียก git ก่อน ซึ่งทำให้ตัวตัดสินไม่ pure) จึงห้ามทั้งหมด — ทางเลือกที่ปลอดภัยคือ `git stash`
- คำสั่งที่ปิดกลไกป้องกันของ Pressure Harness เอง
- **docker/podman ที่ยกเครื่องให้ container**: `--privileged`, `--pid=host`, `--userns=host`,
  `--security-opt seccomp=unconfined` — ถ้าให้ host ไปแล้ว ขอบเขตทุกชั้นเหนือขึ้นไปก็ไม่มีความหมาย
- **mount ที่เอื้อมข้าม workspace**: `-v /:/host`, `/etc`, `/root`, `/var` และ
  **directory ที่เก็บ credential** (`~/.ssh`, `.aws`, `.gnupg`, `.kube`) —
  จับด้วยชื่อ ไม่ใช่ path เต็ม เพราะ `$HOME/.ssh` ไม่ถูก expand โดย parser ของเรา
- **mount `docker.sock`** — ยกซ็อกเก็ตให้ = ยกเครื่องให้
- **ลบ volume**: `docker volume rm/prune`, `compose down -v`, `system prune --volumes`
  — journal ของเราเก็บ pre-image ของ*ไฟล์* **ไม่เคยครอบ volume** ข้อมูล database ที่หายไปคือหายจริง
- **คำสั่งอันตรายที่ซ่อนอยู่ข้างใน container** — `docker exec api rm -rf /`
  ถูกแกะออกมา classify ซ้ำ

**v1 ไม่มี tool ลบไฟล์เลย** — ตรงตามข้อกำหนด "เพิ่ม-อัปเดต-แก้ไขได้ ยกเว้นลบ"
แต่บังคับที่ชั้นโค้ด ไม่ใช่ที่ prompt

### 10.4 ตัวสแกนคำสั่ง (จุดที่ระบบอื่นพลาดบ่อยที่สุด)

การดูแค่คำแรกของคำสั่งไม่พอ ตัวสแกนต้อง:

- **parse จริงตามไวยากรณ์ของ shell นั้น** (`shlex` สำหรับ POSIX, parser แยกสำหรับ PowerShell/cmd)
- แตกคำสั่งซ้อน: `&&`, `||`, `;`, `|`, `$( )`, backtick, newline — แล้วตรวจ **ทุกท่อน**
- **ถือว่าการเรียก interpreter คือความเสี่ยงเต็มขั้นเสมอ**:
  `bash -c`, `sh -c`, `powershell -Command`, `-EncodedCommand`, `cmd /c`,
  `python -c`, `node -e`, `perl -e`, `npx`
- **parse ไม่สำเร็จ = ปฏิเสธ** (fail closed) ห้ามเดา

> หลักฐานว่าข้อนี้จำเป็น: log ของเครื่องมืออ้างอิงมีบรรทัด
> `powershell.exe -NoProfile -Command npm run lint; if (...) { exit ... }; npm run typecheck`
> — allowlist ที่ดูแค่คำแรกจะเห็นเป็น `powershell.exe` แล้วปล่อยผ่านทั้งบรรทัด

### 10.5 ป้องกัน prompt injection

- เนื้อหาจากภายนอก (`web_fetch`, `browser.snapshot`, `browser.console`) ถูกห่อด้วยเครื่องหมาย
  บอกที่มาชัดเจนว่าเป็น **ข้อมูล ไม่ใช่คำสั่ง** (บรรเทาได้ ไม่ใช่กำแพง — จึงต้องมี T3/T4 คุมอีกชั้น)
- `web_fetch` มี domain allowlist; บล็อก `169.254.169.254` (cloud metadata),
  `127.0.0.0/8`, `10/8`, `172.16/12`, `192.168/16` ยกเว้นพอร์ต dev server ที่ผู้ใช้อนุญาต
- **redaction ขาออก**: ทุก output ผ่านตัวกรองลบความลับ (รูปแบบ API key ที่รู้จัก, ค่าใน `.env`,
  string ที่มี entropy สูง) ก่อนส่งกลับ — เพราะทุกอย่างที่ส่งกลับคือการอัปโหลดขึ้น cloud
- **strip env ขาเข้า child process** — ส่งเฉพาะ env ที่ allowlist ไว้ ไม่ส่งทั้ง environment
  (ลง M3 แล้ว) จุดที่ต้องระวังคือ allowlist ต้องครบพอที่โปรแกรมจะรันได้จริง —
  บน Windows ถ้าขาด `SystemRoot`/`PATHEXT` โปรแกรมจะพังแบบงงๆ ซึ่งแย่กว่าพังแบบชัดเจน
  และมี **denylist ที่ส่งต่อไม่ได้แม้ผู้ใช้จะ allowlist เอง** (`LD_PRELOAD`, `DYLD_INSERT_LIBRARIES`,
  `BASH_ENV`, `PYTHONSTARTUP`) เพราะตัวแปรพวกนี้เปลี่ยน *ตัวตน* ของโปรแกรม ไม่ใช่แค่พฤติกรรม

### 10.6 การยืนยันตัวตนของ transport HTTPS

ChatGPT ยอมให้ตั้ง connector แบบ *no authentication* ได้ — **Pressure Harness ต้องไม่รองรับโหมดนั้น**
เพราะใครได้ tunnel URL ไปก็ยึดเครื่องได้

- ใช้ OAuth 2.1 (authorization code + PKCE) เป็นหลัก; รองรับ dynamic client registration
- ถือว่า **tunnel URL เป็นความลับ ไม่ใช่ระบบป้องกัน**
- บันทึกทุก request ที่เข้ามา (IP, เวลา, ผลการ auth) และแสดงในหน้า Connection
- ปุ่มหมุน secret / เพิกถอน client ได้ทันที

**สิ่งที่ลงมือทำใน M7 — และคำถามที่ยากที่สุดของข้อนี้**

OAuth ตอบได้แค่ว่า "client นี้ได้รับอนุญาตแล้ว" แต่ **ใครเป็นคนอนุญาต?**
หน้า consent อยู่หลัง tunnel แปลว่า *ใครก็ตามที่รู้ URL เปิดหน้านั้นได้*

คำตอบที่ใช้: **pairing code ที่พิมพ์อยู่บนคอนโซลของเครื่องนั้นเอง**
ใครก็เปิดหน้า consent ได้ แต่มีแค่คนที่เข้าถึงเครื่องได้เท่านั้นที่อ่านโค้ดได้ —
เป็นหลักการเดียวกับการอนุมัติ tool call นอกแชท เอามาใช้กับตัวการเชื่อมต่อเอง

- โค้ด 8 ตัวอักษร ไม่มี `O/0/I/1/l` เพราะคนต้องอ่านจากจอแล้วพิมพ์ในมือถือ
- เดาผิด 5 ครั้ง = ล็อก 5 นาที (เดา 8 ตัวต้องลองเยอะ ล็อกทำให้การลองมีต้นทุน)
- **โค้ดอยู่ข้ามการ restart** — ระบบความปลอดภัยที่ต้องทำใหม่ทุกครั้งคือระบบที่คนจะปิดทิ้ง
- refresh token ใช้ได้ครั้งเดียว (single-use) — ถ้าถูกขโมยจะใช้ได้แค่จนกว่า client ตัวจริงจะ refresh
  ซึ่งเป็นจังหวะที่การขโมยจะปรากฏตัว
- `ph auth clients` / `ph auth revoke` **ทำงานแยกจาก server** — การเพิกถอนสิทธิ์
  ไม่ควรต้องพึ่งสิ่งที่กำลังจะถูกเพิกถอน

### 10.7 หน้าต่างขออนุมัติ

```
┌─ Pressure Harness ขออนุญาต ───────────── 1:42 ─┐
│ โปรเจกต์: shop      tool: shell      tier: T3   │
│ เหตุผล: คำสั่งไม่อยู่ใน allowlist                │
│                                                  │
│   npx prisma migrate deploy --schema ./db.prisma │  ← payload ดิบ
│                                                  │
│  [ ปฏิเสธ ]  [ ครั้งนี้ ]  [ ทั้ง session ]      │
│              [ จำคำสั่งนี้ไว้ ]                  │
└──────────────────────────────────────────────────┘
```

ข้อกำหนดที่ผูกกับหน้าต่างนี้:

- แสดง **payload ดิบเสมอ** (คำสั่งเต็ม / unified diff / URL) ไม่ใช่คำอธิบายของ AI
- **ไม่มีปุ่ม "อนุญาตทุกอย่าง"** — จะเปิด `full-access` ต้องไปตั้งใน UI อย่างตั้งใจ
- **หมดเวลา 120 วิ = ปฏิเสธอัตโนมัติ** เครื่องที่ไม่มีคนเฝ้าต้องล้มเหลวอย่างปลอดภัย
- การอนุมัติผูกกับ **hash ของ payload นั้นเป๊ะๆ** —
  อนุมัติ `git push origin feature` ไม่ครอบคลุม `git push --force origin main`
- **rate limit**: ถ้าถามเกิน N ครั้ง/นาที → ปฏิเสธอัตโนมัติ + แจ้งเตือน (กัน approval fatigue)
- **ต้องเป็นหน้าต่าง native แยกจากคอนโซล** always-on-top เด้งได้แม้ปิดคอนโซลไปแล้ว
- มี global hotkey เรียกหน้าต่างคิวขึ้นมาได้ทันที

**สิ่งที่ลงมือทำใน M4**

- ทุก tool call เดินผ่าน **gateway** เส้นเดียว: `ตัดสิน → ถาม → รัน → บันทึก`
  ไม่มีทางอื่นไปถึง tool ได้ ซึ่งเป็นสิ่งที่ทำให้ policy engine เป็น *ตัวควบคุม* ไม่ใช่ *คำแนะนำ*
- **notifier ที่ถามไม่ได้ = ปฏิเสธทันที ไม่ใช่รอจนหมดเวลา** — เครื่องที่ไม่มีคนเฝ้า
  ควรได้คำตอบ "ไม่" เดี๋ยวนั้น ไม่ใช่ค้าง 2 นาทีแล้วค่อยไม่
- ลำดับ notifier: หน้าต่าง Tk → console (ถ้า stdin เป็น TTY จริง) → null (ปฏิเสธทุกอย่าง)
- กดปุ่ม X ปิดหน้าต่าง = ปฏิเสธ ไม่ใช่ยกเลิกคำถาม

**เป้าหมายเชิงตัวเลข: ≥95% ของ tool call ต้องผ่านอัตโนมัติ**
ถ้าถามบ่อยกว่านี้ ผู้ใช้จะกด Allow รัวโดยไม่อ่าน ซึ่งแย่กว่าไม่มีระบบเลย

### 10.8 Undo — ตาข่ายที่สำคัญกว่ากฎ

การ "เขียนทับ" ทำข้อมูลหายได้พอๆ กับการลบ ดังนั้น:

- ก่อนแก้ทุกครั้ง เก็บไฟล์เดิมลง journal (`<workspace>/.pharness/journal/`)
- ทำ **git checkpoint** เงียบๆ (shadow ref ไม่รบกวน branch ผู้ใช้) ก่อนแก้เป็นชุด
- `ph undo` และปุ่มย้อนใน UI ย้อนได้ทีละ checkpoint
- journal มีนโยบายหมดอายุ (ค่าเริ่มต้น 14 วัน / 500 MB) และอยู่ใน `.gitignore` เสมอ

**สิ่งที่ตัดสินเพิ่มตอน M2**

- **undo ถูกบันทึกเป็น checkpoint ใหม่ ไม่ใช่การลบ checkpoint เดิม** — ทำให้ย้อน undo ได้อีกที
  และที่สำคัญกว่าคือ ถ้าผู้ใช้แก้ไฟล์เองระหว่างนั้น งานของผู้ใช้จะถูกเก็บไว้ก่อน ไม่หายไปเงียบๆ
  (ถ้าไม่ทำแบบนี้ undo จะกลายเป็นการกระทำเดียวในระบบที่ย้อนไม่ได้)
- **checkpoint เป็น all-or-nothing** — ถ้าล้มกลางคัน ทุกไฟล์ที่แตะไปแล้วถูกคืนสภาพก่อน
  โยน exception ออกไป (patch 3 ไฟล์ที่พังไฟล์ที่ 3 ต้องไม่ทิ้งไฟล์ที่ 1-2 ไว้ครึ่งๆ)
- **`.pharness/` ถูกกันด้วย path jail** — AI อ่านหรือลบประวัติของตัวเองไม่ได้
- **`write_file` ค่าเริ่มต้น `create_only=true`** และรับ `expected_sha` ได้ —
  "เขียนไฟล์นี้" คือวิธีที่ AI ทำงานที่ไม่เคยอ่านหายโดยไม่ตั้งใจ
- **`apply_patch` ตรวจ context เอง** จึงล้มเหลวแทนที่จะทับงานคนอื่นถ้าไฟล์เปลี่ยนไปแล้ว
  และยอมให้เลขบรรทัดคลาดได้ (ค้นหาตำแหน่งที่ context ตรงจริงในระยะ ±200 บรรทัด)
  เพราะโมเดลนับบรรทัดพลาดเป็นเรื่องปกติ แต่ **เนื้อหาต้องตรงเป๊ะเสมอ**
- **รักษา line ending และ encoding เดิมของไฟล์** — ถ้าเขียน LF ทับไฟล์ CRLF
  การแก้ 1 บรรทัดจะกลายเป็น diff ทั้งไฟล์ ซึ่งใช้ไม่ได้จริงบน Windows

### 10.9 Audit log

- JSONL, append-only, **hash chain** (แต่ละบรรทัดมี hash ของบรรทัดก่อนหน้า) → ตรวจการแก้ย้อนหลังได้
- บันทึกทั้งที่อนุญาตและที่ **ถูกปฏิเสธ** (การถูกปฏิเสธคือสัญญาณสำคัญที่สุด)
- แต่ละรายการ: เวลา, session, โปรเจกต์, tool+op, tier, payload hash, ผลการตัดสิน + กฎที่ใช้,
  ระยะเวลา, exit code, ขนาด output
- ตัว payload เต็มเก็บแยกและผ่าน redaction — export ได้พร้อมคำเตือน

### 10.10 ปุ่มหยุดฉุกเฉิน

หนึ่งคลิกจาก tray และ Dashboard: ฆ่า child process ทั้งหมด → ตัด tunnel →
ตีทุกโปรเจกต์กลับเป็น `read-only` → ปฏิเสธคิวที่ค้างอยู่ทั้งหมด

---

## 11. การประหยัดโควตา (Context economy)

ทุก byte ที่ส่งกลับถูกยัดเข้าบทสนทนาและถูกส่งซ้ำในทุกรอบถัดไป
นี่คือจุดที่เครื่องมือแบบนี้พังก่อนจุดอื่น — และเป็นเป้าหมายหลักข้อหนึ่ง (G5)

| กลไก | ค่าเริ่มต้น |
|---|---|
| เพดาน output ต่อ 1 tool call | 8 KB (ตัดหัว/ท้าย พร้อมหมายเหตุว่าตัดไปเท่าไหร่) |
| `read_file` | ต้องระบุช่วงเมื่อไฟล์ใหญ่; คืน outline ให้ก่อนถ้าไฟล์ > เพดาน |
| `search` | คืน `path:line` + snippet 2 บรรทัด, สูงสุด 50 รายการ, มี cursor ขอต่อได้ |
| `git diff` | คืน `--stat` ก่อน แล้วให้ขอ diff รายไฟล์ |
| `process.logs` | คืนเฉพาะ tail; log เต็มอยู่บนดิสก์ |
| screenshot | ย่อขนาด + บีบอัดก่อนส่ง |
| ทุก tool | รองรับ pagination ด้วย cursor |

**มิเตอร์ใน UI** ✅ **ลงแล้ว** — gateway บันทึกขนาดผลลัพธ์ทุกครั้ง คอนโซลรวมเป็นยอดต่อวัน
และแยกตาม tool

ตัวอย่างจริงจากการทดสอบ: `read_file` 4 ครั้ง = **31.8 KB** ส่วน `shell` 4 ครั้ง = **84 B**
— นั่นคือ 75% ของ budget ทั้งวันหมดไปกับ tool เดียว ซึ่งเป็นข้อมูลที่บอกได้ทันทีว่า
ควรไปแก้ที่ค่า default ของตัวไหน สมมติฐาน "ประหยัด quota" ที่ไม่มีใครวัด คือความเชื่อ ไม่ใช่ข้อเท็จจริง

---

## 12. Console UI

**นี่ไม่ใช่ของฟุ่มเฟือย** — เมื่อตัดสินใจว่าการอนุมัติต้องอยู่นอกแชท (§10.1)
ก็ต้องมีที่แสดงคิว ที่เก็บกฎ ที่ถอนกฎ และที่ย้อนดู → UI จึงบังคับมีอยู่แล้ว
tray เป็นเพียงทางเข้า

**หลักการ: ทุกอย่างที่ AI ทำ ผู้ใช้ต้องเห็นได้ หยุดได้ และย้อนได้**
Pressure Harness เป็น *ห้องควบคุม* ไม่ใช่โปรแกรมแชท

### 12.1 หน้าจอ

| # | หน้า | v1 | เนื้อหา |
|---|---|---|---|
| 1 | **หน้าหลัก** | ✅ | สถานะ agent, transport, โหมดสิทธิ์ + นับถอยหลัง, โปรเจกต์ที่ใช้งาน, สถิติวันนี้ (เรียก/ปฏิเสธ/รออนุมัติ), มิเตอร์โควตา, **ปุ่มหยุดฉุกเฉิน** |
| 2 | **โปรเจกต์** | ✅ | รายการ workspace + สิทธิ์รายโปรเจกต์, branch + ไฟล์ค้าง, เพิ่มด้วย folder picker, เตือน scope กว้างเกิน |
| 3 | **การอนุญาต** | ✅ | คิวรออนุมัติ + payload + diff viewer + นับเวลา; ประวัติผ่าน/ไม่ผ่าน + เหตุผล; **จัดการกฎที่เคยกด "จำไว้" และถอนคืนได้** |
| 4 | **กิจกรรม** | ✅ | timeline ทุก tool call: tier, ผลตัดสิน, เวลา, exit code; กดขยายดู payload; กรอง; export; ไฟบอกสถานะ hash chain |
| 5 | **การเชื่อมต่อ** | ✅ | stdio command, tunnel start/stop + URL, auth/หมุน secret, รายการ client ที่ยิงเข้ามา (IP+เวลา), **wizard สอนตั้ง connector ใน ChatGPT** |
| 6 | **Doctor** | ✅ | ตรวจ git/node/python, Chrome debug port, tunnel, config, และ **เตือนการตั้งค่าเสี่ยง**; ปุ่ม export diagnostic bundle (redacted) |
| 7 | **การเปลี่ยนแปลง** | ✅ | checkpoint + before/after diff + ปุ่มย้อน; รวมหน้า git (status/diff/branch/commit) |
| 8 | **Processes** | ✅ | process ที่รันอยู่: cmd, pid, cpu/mem, port, uptime, log tail, ปุ่ม kill |
| 9 | **Live logs** | ✅ | สตรีมดิบสำหรับ debug (รอง จากหน้ากิจกรรม) |
| 10 | **ตั้งค่า** | ✅ | ค่าเริ่มต้น, ภาษา (ไทย/อังกฤษ), ธีม, เปิดตอนบูต, เพดาน output, รูปแบบ redaction, การแจ้งเตือน |

### 12.2 ลำดับการส่งมอบ UI

`การเชื่อมต่อ → โปรเจกต์ → การอนุญาต → กิจกรรม` ให้ครบก่อน
แล้วค่อย `การเปลี่ยนแปลง → Processes → Doctor → หน้าหลัก`

### 12.3 เทคโนโลยี

**เปลี่ยนจากแผนเดิมตอน M5 (และดีขึ้น):** แทนที่จะเป็น pywebview ล้วน คอนโซลถูกทำเป็น
**local web app** ที่ serve บน loopback พร้อม token — ส่วน pywebview เหลือเป็นแค่กรอบหน้าต่าง
ที่เปิดหน้าเดียวกันนั้น เหตุผล:

- **ทดสอบได้จริง** — ผมยิง API ได้ทุก endpoint และ **เปิดดู+ถ่ายภาพหน้าจอทุกหน้าได้ด้วย
  browser tool ของโปรเจกต์เอง** ซึ่งเป็นสิ่งที่หน้าต่าง Tk ทำไม่ได้ (ดู MANUAL-CHECKS §1)
- **degrade ได้** — เครื่องที่ไม่มี GUI toolkit ยังใช้คอนโซลได้ แค่เปิด URL ในเบราว์เซอร์
- **หน้าเดียวจบ ไม่มี build step** — คอนโซลที่ต้องมี toolchain ก่อนถึงจะดูได้ว่าเครื่องกำลังทำอะไร
  คือคอนโซลที่จะพังวันที่ toolchain พัง

**ข้อกำหนดด้านความปลอดภัยของคอนโซล**

- **bind loopback เท่านั้น และมี token** — คอนโซลคือที่ที่*ให้*และ*ยึด*สิทธิ์
  จึงต้องไม่มีทางเข้าถึงผ่าน tunnel ที่เปิดให้ tool; และ loopback ก็ยังหมายถึง
  ทุกโปรแกรมอื่นบนเครื่องเดียวกัน จึงต้องมี token ด้วย
- **คอนโซลรันในโปรเซสเดียวกับ server** — เพราะคิวอนุมัติอยู่ในหน่วยความจำ
  คอนโซลแยกโปรเซสจะเห็นได้แค่สิ่งที่อยู่บนดิสก์
- **หน้าต่างขออนุมัติ: native ของแต่ละ OS** แยกจากคอนโซล เพื่อให้ always-on-top และ
  เด้งได้แม้คอนโซลปิดอยู่ (ข้อกำหนดจาก §10.7)
- **tray**: `pystray` (Windows) / menu bar adapter แยกสำหรับ macOS
- หลีกเลี่ยง web API แปลกๆ เพื่อให้ WKWebView แสดงผลเหมือนกัน

> **ต้นทุน**: UI กินแรงประมาณ 40% ของงาน v1 — ยอมรับ เพราะระบบอนุมัติไม่มี UI ไม่ได้

---

## 13. ตัวอย่างการทำงานเต็มรอบ

ผู้ใช้พิมพ์: *"ปุ่ม login กดแล้วไม่ทำงาน ช่วยดูให้"*

| # | tool | tier | ผล |
|---|---|---|---|
| 1 | `search text "login"` | T0 | auto |
| 2 | `read_file src/Login.tsx` | T0 | auto |
| 3 | `project dev` | T2 | auto (อยู่ใน allowlist) |
| 4 | `browser navigate localhost:3000` | T2 | auto |
| 5 | `browser click` + `browser console` | T2 | เจอ `TypeError: onSubmit is not a function` |
| 6 | `apply_patch` | T1 | auto + สร้าง checkpoint |
| 7 | `project test` | T2 | auto |
| 8 | `browser screenshot` | T2 | ส่งภาพกลับให้ยืนยันด้วยตา |
| 9 | `git commit` | T1 | auto |
| 10 | `git push` | T4 | **ถาม** → ผู้ใช้กดอนุมัติที่หน้าเครื่อง |

---

## 14. สถาปัตยกรรมข้ามแพลตฟอร์ม

เป้าหมาย: v1 ส่ง Windows แต่ **โครงต้องพร้อมพอร์ตไป macOS แล้ว Linux** โดยไม่รื้อ core

### 14.1 โครงโฟลเดอร์

> โครงจริงที่ลงมือทำใน M1 อยู่ใต้ `src/pharness/` เพื่อให้ติดตั้งเป็นแพ็กเกจได้
> (`src/pharness/core`, `src/pharness/ports`, `src/pharness/adapters`, `src/pharness/ui`)

> **แก้โครงตอน M6:** `runtime.py` (ตัวประกอบร่าง) และ `mcp/` (ผิวสัมผัสกับ client)
> ถูกย้าย**ออกจาก** `core/` ไปอยู่ระดับ `src/pharness/` เพราะการประกอบร่างจำเป็นต้อง
> เอ่ยชื่อแพลตฟอร์ม ซึ่งเป็นสิ่งที่ `core/` ห้ามทำ — **import-linter เป็นตัวจับได้**
> ไม่ใช่คนมานั่งทบทวนไดอะแกรม

```
core/            ← ไม่รู้จัก OS เลย  (~70-75% ของโค้ด)
  mcp/           protocol, tool registry, session
  policy/        tier, rules, path jail, ตัวตัดสิน
  workspace/     จัดการโปรเจกต์, config
  audit/         log + journal/undo
  tools/         read_file, search, apply_patch, git, browser, web_fetch, ...

ports/           ← interface ล้วน (Python Protocol) ไม่มี implementation
  process.py     spawn / kill tree / stream
  shell.py       parse + สแกนคำสั่ง
  paths.py       ที่เก็บ config, normalize, ตรวจ symlink หลุด
  notifier.py    หน้าต่างอนุมัติ + notification
  autostart.py   เปิดตอนบูต
  browser.py     หา/เปิด Chrome
  tray.py

adapters/
  windows/       ← v1 ทำเฉพาะอันนี้
  macos/         ← v1 มีแค่โครงที่ raise NotImplementedError
  posix/         ← ส่วนที่ mac + linux ใช้ร่วมกัน

ui/              ← HTML/CSS/JS ใช้ร่วมทุกแพลตฟอร์ม
```

เลือก adapter ตอน startup ครั้งเดียวตาม `sys.platform` — core ไม่ต้องรู้อะไรอีก

### 14.2 กฎที่บังคับด้วยเครื่อง ไม่ใช่ด้วยวินัย

- **ห้าม `if sys.platform == ...` ใน `core/`** — บังคับด้วย `import-linter` ใน CI:
  `core/` ห้าม import `winreg`, `pywin32`, `adapters/*` → ละเมิดเมื่อไหร่ CI แดง
- **contract test ต่อ port** — เทสต์ชุดเดียวรันกับทุก adapter
  ตอนเขียน macOS adapter จะมีเทสต์รออยู่แล้ว ไม่ต้องเดา
- **รัน CI ของ `core/` บน Windows + macOS + Linux ตั้งแต่ v1** ทั้งที่ยังไม่รองรับ
  เพื่อจับบั๊ก path / encoding / line-ending ตั้งแต่วันแรก (แทบไม่มีต้นทุนเพิ่ม)

### 14.3 Capability manifest

tool registry ต้องสร้าง **ตอน runtime** จาก capability ที่ adapter ประกาศ
ห้ามเป็น list ตายตัว — ถ้าประกาศ tool ที่แพลตฟอร์มนั้นทำไม่ได้ AI จะเรียกแล้ว error วนไป
กินทั้งโควตาและความน่าเชื่อถือ

### 14.4 สิ่งที่ต่างกันจริงและต้องเขียนแยก (~25%)

| ส่วน | Windows | macOS | ระดับ |
|---|---|---|---|
| shell + ตัวสแกนคำสั่ง | cmd / PowerShell | zsh / bash | 🔴 กฎ quoting คนละระบบ ต้องเขียน parser แยก |
| kill process tree | `taskkill /T` | process group + SIGTERM/SIGKILL | 🟡 |
| path | drive letter, `CON`/`NUL`, junction | ไม่มี drive letter, symlink/firmlink | 🟡 |
| หน้าต่างอนุมัติ / tray | Win32, pystray | NSWindow, menu bar (main thread) | 🟡 |
| เปิดตอนบูต | Registry Run / Task Scheduler | LaunchAgent plist | 🟢 |
| ที่เก็บ config | `%APPDATA%\PressureHarness` | `~/Library/Application Support/PressureHarness` | 🟢 |
| การแพ็ก/เซ็น | PyInstaller (+cert ถ้ามี) | .app + codesign + **notarize** | 🔴 ต้นทุน/ขั้นตอน |
| สิทธิ์ระบบ | ไม่ต้องขอ | TCC: Screen Recording / Accessibility / Full Disk Access | 🔴 กระทบ Phase 2 |

**Phase 2 (Office COM, UI Automation) ย้ายไม่ได้** — ของเทียบเคียงบน mac คือ
AppleScript / Accessibility API ซึ่งถือว่า *เขียนใหม่* ไม่ใช่ *พอร์ต*

### 14.5 ต้นทุน

| ทางเลือก | ต้นทุน |
|---|---|
| วางโครง ports ตั้งแต่ v1 (ทำแค่ Windows adapter) | **+10-15%** ของงาน v1 ← **เลือกทางนี้** |
| เขียนตรงๆ แล้วมารื้อทีหลัง | 2-3 เท่าของข้างบน + ความเสี่ยงว่า policy engine มีรูตอนรื้อ |

**ไม่เขียน macOS adapter ใน v1** — abstraction ที่ยังไม่เคยถูกใช้จริงมักออกแบบผิด
สิ่งที่ทำตอนนี้คือวางเส้นแบ่งให้ถูก + บังคับด้วย CI + มี contract test รอไว้

ผลพลอยได้: เมื่อมี `posix/` แล้ว **Linux ได้มาเกือบฟรี** (เหลือแค่ tray + notification)

---

## 15. Config

ที่อยู่: `%APPDATA%\PressureHarness\config.toml` (Windows) — **AI เข้าถึงไม่ได้ (T5)**
แก้ได้จาก UI / CLI / แก้ไฟล์เอง เท่านั้น

```toml
[server]
bind = "127.0.0.1"
port = 18765

[security]
default_mode          = "auto-edit"   # ห้ามเป็น full-access
full_access_ttl_min   = 120
approval_timeout_sec  = 120
approval_rate_limit   = 10            # ต่อนาที
redact_secrets        = true

[context]
max_output_bytes = 8192
search_max_hits  = 50

[[workspace]]
alias    = "shop"
path     = 'D:\work\my-shop-web'
mode     = "auto-edit"
git_push = false
allow_commands = ["npm test", "npm run build", "git status", "git diff"]

[workspace.scripts]
dev = "npm run dev"
test = "npm test"
lint = "npm run lint"

[[workspace]]
alias = "api"
path  = 'D:\work\api'
mode  = "read-only"

[network]
fetch_allowlist = ["docs.python.org", "developer.mozilla.org"]

[tunnel]
provider   = "cloudflared"
auth       = "oauth"      # ห้ามตั้งเป็น "none"
autostart  = false
```

---

## 16. ข้อกำหนดที่ไม่ใช่ฟีเจอร์ (NFR)

| ด้าน | ข้อกำหนด |
|---|---|
| แพลตฟอร์ม v1 | Windows 10/11 x64; Python 3.11+ |
| ประสิทธิภาพ | tool อ่าน p95 < 300 ms; startup < 2 วิ; RAM ตอน idle < 200 MB |
| สิทธิ์ระบบ | รันด้วยสิทธิ์ผู้ใช้ปกติ — **ปฏิเสธที่จะ start ถ้าถูกรันแบบ Administrator** |
| ความทนทาน | tunnel หลุดแล้วต่อกลับเอง; เครื่อง sleep แล้วฟื้นได้; process ที่ค้างถูกเก็บกวาดตอน start |
| ความเป็นส่วนตัว | ไม่มี telemetry; ไม่มีการส่งข้อมูลออกนอกเครื่องนอกจากไปยัง ChatGPT ผ่าน transport ที่ผู้ใช้ตั้ง |
| i18n | ไทย + อังกฤษ ตั้งแต่ v1 |
| การเข้าถึง | คอนโซลใช้คีย์บอร์ดล้วนได้; หน้าต่างอนุมัติมี global hotkey |
| ทดสอบ | `core/` coverage ≥ 80%; policy engine + path jail ต้องมี property/fuzz test |

---

## 17. การแจกจ่าย

เป้าหมายระยะยาวคือแจกให้คนอื่นใช้ (Windows → macOS → Linux) ซึ่งเปลี่ยนข้อกำหนดบางข้อ:

- **ค่าเริ่มต้นต้องปลอดภัย ไม่ใช่สะดวก** — บนเครื่องตัวเองผู้เขียนรับความเสี่ยงเองได้
  บนเครื่องคนอื่นไม่ได้ → ห้ามมี `unrestricted` เป็นค่าเริ่มต้น
- **การเซ็นโค้ด** — Windows ไม่เซ็นจะโดน SmartScreen เตือน (cert ~$100-400/ปี);
  macOS ไม่ notarize จะเปิดไม่ได้เลย ($99/ปี)
  → ระยะแรกแจกผ่าน **winget / scoop / pipx / brew** และบอกวิธีตรวจ checksum อย่างชัดเจน
- **ห้ามมี auto-updater ที่รันโค้ดที่ดาวน์โหลดมาโดยไม่ตรวจลายเซ็น** —
  v1 ใช้ "แจ้งเตือนว่ามีเวอร์ชันใหม่ + ให้ผู้ใช้อัปเดตเอง"
- ต้องมี `SECURITY.md` (ช่องทางรายงานช่องโหว่), `THREAT_MODEL.md`
- **license: Apache-2.0** (ยืนยันแล้ว — ไฟล์ `LICENSE` ที่รากของ repo)
- **ชื่อผลิตภัณฑ์** — `Pressure Harness` ไม่ชนเครื่องหมายการค้าใคร ใช้ "for ChatGPT"
  ต่อท้ายได้ แต่ห้ามเอา ChatGPT/Codex/Claude ไปเป็นส่วนหนึ่งของชื่อ (ดู §23 ที่มาของชื่อ)
- **ต้องมี tagline คู่ชื่อเสมอ** — คำว่า "pressure" ทำให้คนในวงการเดาไปทาง load/stress testing
  ก่อนเป็นอันดับแรก tagline จึงต้องอยู่คู่ชื่อในทุกที่ที่แนะนำตัว (README, เว็บ, โพสต์)
- ปุ่ม **export diagnostic bundle** (ผ่าน redaction แล้ว) เพื่อลดภาระซัพพอร์ต

---

## 18. การประเมินเครื่องมืออ้างอิง

ประเมินจากโพสต์ที่ผู้ใช้แชร์ + ภาพหน้าจอแอป `lnwjud`

**สิ่งที่เขาทำถูกและเรารับมาใช้**

- ใช้ custom MCP connector — เป็นช่องทางที่ถูกต้องตามที่ OpenAI เปิดให้
- tunnel แบบ outbound-only ไม่ต้องเปิด port ที่ router — **ถูกต้อง**
- แยกหน้า Tunnel / MCP activity / Processes; มีหน้า **Doctor** (ฉลาด ลดงานซัพพอร์ต); ทำ 2 ภาษา
- ไอเดีย `codex_run` — ให้ ChatGPT มอบงานหนักต่อให้ local CLI (เข้ากับเป้าหมายประหยัดโควตา)

**สิ่งที่ต้องแก้ความเข้าใจ**

- *"OpenAI Secure MCP Tunnel"* — ไม่มีผลิตภัณฑ์ชื่อนี้ ของจริงคือ remote MCP over HTTPS
  ผ่าน tunnel ทั่วไป (cloudflared/ngrok) หรือ stdio ผ่าน desktop app
- *"Quota เหลือ 100%"* — เกินจริง; tool output ถูกยัดเข้า context ทุกก้อน (จึงเกิด §11)

**ช่องโหว่ที่เราจะไม่ทำตาม**

| ที่เห็น | ปัญหา |
|---|---|
| `ACTIVE PROJECT: Local Disk E:` | ให้ทั้งไดรฟ์เป็น workspace → path jail ไร้ความหมาย |
| `WORK mode · Unrestricted` | ไม่มีโหมดสิทธิ์ ไม่มีการขออนุมัติเลย |
| เพิ่มโปรเจกต์โดยพิมพ์ path ลงช่องข้อความ | ไม่มีขั้นตอนตั้งสิทธิ์ตอนเพิ่ม |
| log แบน มีแค่ STARTED/SUCCESS | ดูย้อนหลังได้ แต่แทรกแซงไม่ได้ ไม่เห็น payload/diff ไม่มีปุ่มปฏิเสธ |
| `powershell.exe -NoProfile -Command npm run lint; if (...)` | ยืนยันว่าช่องหนี interpreter เกิดขึ้นจริงในการใช้งานปกติ (§10.4) |
| tunnel ถูก start จากสคริปต์ภายนอก | แอปคุมสถานะตัวเองไม่ได้ |

**สรุป:** ของเขาเป็น *หน้าต่างเฝ้าดู* — Pressure Harness ต้องเป็น *หน้าต่างควบคุม*
ความต่างคือหยุด ปฏิเสธ และย้อนได้จริง

---

## 19. แผนงาน

| Milestone | เนื้อหา | ผลลัพธ์ที่พิสูจน์ได้ |
|---|---|---|
| **M0 — Spike** ⚠️ | MCP server จิ๋ว 6 tool + tunnel — โค้ดอยู่ที่ `spike/`, วิธีทำการทดลองอยู่ที่ [docs/M0-SPIKE.md](M0-SPIKE.md) | ตอบ OQ-1..4 ใน §20 **ก่อนลงทุนสร้างของจริง** |
| M1 — Core ✅ | ports layer, config, workspace, path jail, policy engine, audit log, `ph` CLI + CI 3 OS | **เสร็จแล้ว** — 200 tests, core coverage 91%, contract test ต่อ port, fuzz test, import-linter บังคับเส้นแบ่ง OS |
| M2 — Files ✅ | read/search/write/apply_patch + journal + undo + `ph undo`/`ph checkpoints` | **เสร็จแล้ว** — 264 tests, core coverage 92%; patch engine เขียนเอง (ตรวจ context, ทนเลขบรรทัดคลาด, atomic ข้ามไฟล์), รักษา CRLF/encoding, undo ย้อนได้เอง |
| M3 — Dev loop ✅ | git, project runners, process manager, `ProcessPort` ทั้ง Windows/POSIX, env allowlist | **เสร็จแล้ว** — 318 tests, core coverage 92%; ฆ่า process ทั้งต้นไม้ได้จริง (มีเทสต์ยืนยันว่า grandchild ตายด้วย) |
| M4 — Exec + Approval ⚠️ | shell tool, คิวอนุมัติ, gateway (decide→ask→run→audit), หน้าต่าง Tk, console notifier | **โค้ดเสร็จ 348 tests** แต่ **หน้าต่าง Tk ยังไม่ถูกยืนยันบนเครื่องจริง** (คอนเทนเนอร์ไม่มี display) → ดู [MANUAL-CHECKS.md](MANUAL-CHECKS.md) §1 |
| M5 — Console UI ✅ | 8 หน้า: Overview, Approvals, Projects, Activity, Changes, Processes, Connection, Doctor | **เสร็จแล้ว** — เป็น local web app (loopback + token) ไม่ใช่ pywebview ล้วน จึง **ทดสอบและ screenshot ได้จริง** |
| M6 — Browser ✅ | CDP client เขียนเอง + browser tool 9 op + web_fetch | **เสร็จแล้ว** — ทดสอบกับ Chromium จริง: navigate → click → อ่าน `ReferenceError: onSubmit is not defined` ที่หน้าเว็บโยนออกมาจริง → screenshot |
| M7 — Transport ✅ | tool catalogue 13 ตัว, gateway ต่อเข้ากับ MCP, `ph serve` (stdio / HTTP), **OAuth 2.1 + pairing code**, ตัวจัดการ tunnel | **เสร็จแล้ว** — เดิน OAuth ครบทุกขั้นกับ server จริง: discovery → DCR → consent → PKCE → token → refresh rotation |
| M8 — Ship | UI ที่เหลือ, แพ็ก, onboarding wizard, เอกสาร | P2 ติดตั้งใช้ได้ใน 10 นาที |
| M9 — macOS | เขียน `adapters/macos/` ตาม contract test ที่มีอยู่ | — |
| Phase 2 | desktop automation, GitHub, mobile approval + PIN | — |

> **M0 สำคัญที่สุดในแผน** — ถ้าข้อจำกัดใน §20 เป็นจริง มันเปลี่ยนคุณค่าของผลิตภัณฑ์
> ต้องรู้ก่อนสร้าง tool ครบ 14 ตัว

---

## 20. ความเสี่ยงและคำถามที่ยังไม่มีคำตอบ

> การทดลองที่ใช้ตอบ OQ-1..4 และตารางบันทึกผล อยู่ใน [docs/M0-SPIKE.md](M0-SPIKE.md)
> เมื่อได้ผลแล้วให้แปลง OQ แต่ละข้อในตารางนี้เป็นข้อสรุป

| # | คำถาม / ความเสี่ยง | ผลกระทบ | แผนรับมือ |
|---|---|---|---|
| OQ-1 | **MCP write action ถูกปิดบนแอปมือถือ ChatGPT หรือไม่** (แหล่งข้อมูลขัดกัน) | สูง — กระทบการใช้จากมือถือ | ทดสอบใน M0; ถ้าจริง → ใช้เว็บบนมือถือแทนแอป และยอมรับว่าอ่าน/ตรวจได้จากมือถือ **ห้ามหลบด้วยการติดป้าย tool ผิด** |
| OQ-2 | ChatGPT แสดงผล **image content** ที่ MCP tool ส่งกลับได้ไหม | กลาง — กระทบ screenshot | ทดสอบใน M0; fallback = บันทึกไฟล์ + คืน path, หรือส่งข้อความสรุป |
| OQ-3 | มีเพดานจำนวน tool / ขนาด schema ของ connector ไหม | กลาง | ทดสอบใน M0; ออกแบบเป็น ~14 tool ที่มี `op` อยู่แล้ว |
| OQ-4 | ข้อกำหนด OAuth/DCR ของ ChatGPT connector ที่แน่นอน | กลาง | ทดสอบใน M0-M7 |
| R-1 | **Prompt injection → รันคำสั่ง** | **สูงสุด** | tier + allowlist + อนุมัตินอกแชท + ห่อเนื้อหาภายนอก + undo (§10) |
| R-2 | Approval fatigue → ผู้ใช้กด Allow รัว | สูง | เป้า auto-allow ≥95%, rate limit, ไม่มีปุ่ม "อนุญาตทุกอย่าง" |
| R-3 | OpenAI เปลี่ยน/ปิดฟีเจอร์ connector | สูง | tool layer แยกจาก transport — ยังใช้กับ Claude Code/Codex CLI ผ่าน stdio ได้ |
| R-4 | tunnel URL รั่ว | สูง | บังคับ OAuth, หมุน secret ได้, log ผู้เชื่อมต่อ, ปุ่มตัด tunnel |
| R-5 | Windows Defender / SmartScreen เตือนไฟล์ที่แพ็ก | กลาง | เซ็นโค้ด หรือแจกผ่าน package manager (§17) |
| R-6 | โควตาหมดเร็วกว่าที่คาด | กลาง | §11 + มิเตอร์ให้ผู้ใช้เห็นของจริง |
| R-7 | ผู้ใช้ตั้ง workspace เป็นทั้งไดรฟ์ (เหมือนของอ้างอิง) | สูง | เตือนตอนเพิ่ม + Doctor เตือนซ้ำ |

---

## 21. ตัวชี้วัดความสำเร็จ

| ตัวชี้วัด | เป้า v1 |
|---|---|
| tool call ที่ผ่านอัตโนมัติ | ≥ 95% |
| เวลาตอบสนองหน้าต่างอนุมัติ (median) | < 10 วิ |
| p95 ของ tool อ่าน | < 300 ms |
| ขนาด output เฉลี่ยต่อ tool call | < 4 KB |
| การหลุดออกนอก workspace ใน fuzz test | **0** |
| เวลาที่ผู้ใช้ใหม่ (P2) ติดตั้งจนใช้งานได้ | < 10 นาที |
| งานจริงที่ทำจบได้โดยไม่ต้อง copy-paste โค้ดเอง | ≥ 80% |

---

## 22. ภาคผนวก — คำที่ใช้ในเอกสาร

- **MCP** — Model Context Protocol มาตรฐานให้ AI เรียกใช้เครื่องมือภายนอก
- **MCP server** — โปรแกรมที่ *ให้บริการ* tool (ในที่นี้คือ Pressure Harness บนเครื่องผู้ใช้ ไม่ใช่เซิร์ฟเวอร์ในดาต้าเซ็นเตอร์)
- **stdio / Streamable HTTP** — ช่องทางที่ MCP client คุยกับ server
- **CDP** — Chrome DevTools Protocol โปรโตคอลเดียวกับที่ DevTools ใช้
- **tier (T0-T5)** — ระดับความเสี่ยงของการกระทำ ดู §10.3
- **checkpoint** — จุดย้อนกลับที่ Pressure Harness สร้างก่อนแก้ไฟล์เป็นชุด
- **prompt injection** — การฝังคำสั่งในเนื้อหาที่ AI อ่าน เพื่อหลอกให้ทำสิ่งที่เจ้าของไม่ได้สั่ง

---

## 22b. ผลการตรวจความปลอดภัยหลังเขียนเสร็จ

ตรวจทั้ง codebase หลังจบ v1 โดยไล่ตามพื้นที่โจมตี (ดู [THREAT_MODEL.md](THREAT_MODEL.md))
สิ่งที่เจอและแก้แล้ว:

| ระดับ | สิ่งที่เจอ | แก้อย่างไร |
|---|---|---|
| **สูง** | **`browser navigate file:///...` อ่านไฟล์ได้ทั้งเครื่อง** — `_is_local()` นับ `file://` เป็น local จึงข้าม allowlist และไม่เคยผ่าน path jail เลย พิสูจน์แล้วว่าอ่านไฟล์นอก workspace ได้จริง | ทุก URL ผ่าน `check_url()`; `file://` ต้องผ่าน jail เดียวกับ `read_file`; scheme อย่าง `view-source:`/`chrome:`/`javascript:` ถูกปฏิเสธ |
| **กลาง-สูง** | **`package.json` ของ repo กำหนดให้ `npm test` ทำอะไรก็ได้** — ตัวสแกนเห็นแค่ 2 คำที่ไม่มีพิษภัย ถ้า `npm test` อยู่ใน allowlist ก็รันทันที | classify **เนื้อของ script** ไม่ใช่ชื่อ task — ทดสอบแล้วว่า `"test": "rm -rf ~"` ถูกปฏิเสธแม้ `npm test` จะ allowlist ไว้ |
| กลาง | `notify` ส่งข้อความอะไรก็ได้ขึ้น desktop notification โดยไม่บอกที่มา = ช่องหลอกขอ pairing code | ขึ้นต้นด้วย "From the assistant:" เสมอ — ข้อความของโมเดลต้องไม่ถูกเข้าใจผิดว่าเป็นของซอฟต์แวร์เอง |
| ต่ำ | `esc()` ในคอนโซลไม่ escape `'` ซึ่งค่าบางตัวไปอยู่ใน inline handler | escape `'` ด้วย — ปิดทั้งคลาส ไม่ใช่ปิดเฉพาะเคส |
| ต่ำ | `activity(limit)` ไม่จำกัดเพดาน | clamp ที่ 500 |

**ตรวจแล้วไม่พบปัญหา:** OAuth client_id เป็น uuid ที่ server สร้าง (ไม่มี injection),
payload hash ครอบทุก tool ที่รับ input อันตราย, `git add` ปฏิเสธ path ที่ขึ้นต้นด้วย `-`,
`screenshot` ตัด directory ออกจากชื่อไฟล์, console `_coerce` ส่งได้เฉพาะ parameter ที่ประกาศไว้

**ความเสี่ยงที่ยอมรับและบันทึกไว้** (ดู THREAT_MODEL §Known gaps): DNS rebinding
ระหว่างเช็คกับต่อจริง, TOCTOU ระหว่าง resolve path กับเปิดไฟล์, และการล็อก pairing code
ที่ทำให้เจ้าของถูก DoS ได้ (แก้ด้วย `ph auth rotate`)

---

## 23. ที่มาของชื่อ และการใช้คำว่า "harness"

บันทึกไว้เพื่อให้เอกสาร/README/หน้าเว็บใช้คำให้ตรงกัน และไม่อธิบายตัวเองผิดความหมาย

### 23.1 ทำไมโปรเจกต์นี้เป็น harness จริง

คำว่า harness มี 3 ความหมายที่ใช้กันอยู่ — ของเราตรง 2 เลี่ยง 1

| ความหมาย | ตรงไหม | เหตุผล |
|---|---|---|
| **สายรัดม้า / สายเซฟตี้** (ดั้งเดิม) | ✅ ตรง เป็นที่มาของอุปมา | แกนความหมายคือ *เชื่อมแหล่งพลังเข้ากับงาน พร้อมบังคับทิศและจำกัดขอบเขตไปด้วยในตัว* |
| **agent harness** (วงการ AI) | ✅ **ตรงที่สุด — ใช้ความหมายนี้เป็นหลัก** | โครงที่ห่อโมเดลไว้แล้วให้ tool / loop / ระบบสิทธิ์ จนโมเดลทำงานจริงได้ (Claude Code, Codex CLI อยู่หมวดนี้) |
| **test harness** (วงการซอฟต์แวร์) | ❌ **ไม่ตรง — ห้ามใช้อธิบายตัวเอง** | test harness มีไว้ *ยืนยันความถูกต้องของสิ่งที่ถูกทดสอบ* เราไม่ได้ทดสอบ ChatGPT เราเอา ChatGPT ไปทำงาน |

การจับคู่กับสถาปัตยกรรมของเรา:

| องค์ประกอบของ harness | ในโปรเจกต์นี้ |
|---|---|
| แหล่งพลัง | ChatGPT — ทรงพลังแต่ไม่มีมือ |
| งานที่ต้องลาก | โค้ดและเครื่องของผู้ใช้ |
| สายที่เชื่อมสองฝั่ง | MCP tool layer (§8) |
| **บังเหียนและสายจำกัดระยะ** | policy engine, path jail, tier, การขออนุมัติ (§10) |
| คนถือบังเหียน | ผู้ใช้ที่หน้าเครื่อง |

**ประเด็นสำคัญ:** MCP server ทั่วไปที่แค่ต่อ tool ให้ AI **ไม่ใช่ harness** — มันคือ bridge หรือ
gateway เพราะมีแต่สายลาก ไม่มีสายรัด สิ่งที่ทำให้โปรเจกต์นี้เป็น harness จริงคือ §10
ซึ่งกินพื้นที่เอกสารมากที่สุดและเป็นความต่างหลักจากเครื่องมืออ้างอิงใน §18

### 23.2 กฎการใช้คำ

- ในเอกสารและหน้าแนะนำตัว ใช้ว่า **"local coding agent harness"** ไม่ใช่ "bridge" หรือ "gateway"
- ห้ามอธิบายตัวเองด้วยคำที่ชวนให้เข้าใจเป็น test/load tool เช่น "stress", "benchmark", "pressure test"
- **ห้ามเอาอุปมา harness ไปตั้งชื่อโมดูลในโค้ด** — ใช้ `policy.py`, `path_jail.py`, `approval.py`
  ไม่ใช่ `reins.py`, `bridle.py`, `tether.py` ชื่อสวยในโค้ดแลกด้วยต้นทุนการอ่านที่สูงเกินคุ้ม
- ชื่อ CLI: `ph` (ย่อ) — package/binary: `pharness`
