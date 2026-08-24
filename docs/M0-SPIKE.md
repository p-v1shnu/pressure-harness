# M0 — Spike: ทดสอบสมมติฐานก่อนสร้างของจริง

**สถานะ:** โค้ดพร้อมรัน — รอผลการทดลองจากเครื่อง Windows ของเจ้าของโปรเจกต์

เป้าหมายเดียวของ M0 คือตอบ **OQ-1 ถึง OQ-4** ใน [PRD §20](PRD.md) ให้ได้
ก่อนจะลงทุนสร้าง tool ครบ 14 ตัวตาม §8 — เพราะถ้าสมมติฐานผิด มันเปลี่ยนขอบเขต
ของ M6 (browser/screenshot) และ M8 (การใช้จากมือถือ) อย่างมีนัยสำคัญ

> **นี่คือโค้ดทิ้ง ไม่ใช่รากฐาน** — spike ตั้งใจไม่มี policy engine, audit log,
> approval queue และ OAuth ตาม PRD ห้ามเอาไปต่อยอดเป็น v1

---

## 1. สิ่งที่ spike ทำและไม่ทำ

| | |
|---|---|
| ✅ พูด MCP ได้ทั้ง **stdio** และ **Streamable HTTP** | เพื่อทดสอบทั้ง 2 ช่องทางใน PRD §7 |
| ✅ มี tool 6 ตัว แต่ละตัวผูกกับคำถามที่ต้องตอบ | ดู §4 |
| ✅ ทุก tool ที่แตะไฟล์ถูกขังใน `spike/spike-sandbox/` | มี path jail จริงย่อส่วน — ออกนอกไม่ได้ |
| ✅ ปฏิเสธการ bind ที่ไม่ใช่ loopback | ป้องกันการเปิดพอร์ตออกเน็ตโดยไม่ตั้งใจ |
| ✅ log ทุก HTTP request (ซ่อน token) | เพื่อดูว่าเซิร์ฟเวอร์ OpenAI ยิงมาหน้าตาแบบไหน |
| ❌ ไม่มีระบบขออนุมัติ / audit log / undo | เป็นงานของ M1-M5 |
| ❌ ไม่มี OAuth | ใช้ secret ใน URL path แทนชั่วคราว — ดู §6 |

---

## 2. ติดตั้ง

ต้องมี Python 3.11+ บน PATH (`py -3 -V` ต้องขึ้นเวอร์ชัน)

```
cd spike
setup.cmd
```

ถ้าไม่ใช้ Windows: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`

---

## 3. ขั้นตอนที่ 1 — ทดสอบในเครื่องก่อน (บังคับ)

```
selftest.cmd
```

ต้องได้ `all checks passed` (17 checks) **ก่อน** ไปยุ่งกับ ChatGPT
ถ้าตกที่ขั้นนี้ = บั๊กของเรา ถ้าผ่านขั้นนี้แล้วไปตกใน ChatGPT = ข้อค้นพบเรื่องแพลตฟอร์ม
การแยกสองอย่างนี้ออกจากกันคือเหตุผลทั้งหมดที่ M0 มีอยู่

ทดสอบ padding tools ด้วย: `selftest.cmd --extra-tools 40`

---

## 4. tool ทั้ง 6 ตัว และคำถามที่มันตอบ

| tool | annotation | ใช้ตอบ |
|---|---|---|
| `spike_read_file` | `readOnlyHint: true` | **OQ-1 กลุ่มควบคุม** — tool อ่านควรทำงานได้ทุกที่ |
| `spike_write_file` | `readOnlyHint: false`, `destructiveHint: false` | **OQ-1** — การเขียนแบบไม่ทำลายถูกบล็อกบนมือถือไหม |
| `spike_overwrite_file` | `readOnlyHint: false`, `destructiveHint: **true**` | **OQ-1 แขนที่สอง** — ข้อจำกัดดูที่ `destructiveHint` หรือดูที่ "เขียน" เฉยๆ |
| `spike_return_image` | `readOnlyHint: true` | **OQ-2** — ChatGPT แสดงรูปที่ MCP tool ส่งกลับได้ไหม |
| `spike_echo` | `readOnlyHint: true` | **PRD §11** — output ถูกตัดที่เท่าไหร่ |
| `spike_whoami` | `readOnlyHint: true` | **OQ-4** — protocol version, ตัวตน client, header ที่ส่งมา |
| `spike_pad_NNN` (สั่งเพิ่มได้) | `readOnlyHint: true` | **OQ-3** — เพดานจำนวน tool ของ connector |

`spike_write_file` กับ `spike_overwrite_file` มีรูปร่างเหมือนกันเป๊ะ ต่างกันแค่
annotation กับพฤติกรรมจริง — ออกแบบมาเพื่อ **แยกตัวแปรเดียว** ให้ได้

> หมายเหตุด้านความซื่อสัตย์: `spike_overwrite_file` ทำลายข้อมูลจริง (เขียนทับไฟล์เดิม)
> จึงติดป้าย `destructiveHint: true` ตามความจริง — เราไม่ติดป้ายผิดเพื่อทดลอง
> ตาม PRD §4

---

## 5. ขั้นตอนที่ 2 — ต่อ stdio (ง่ายกว่า เริ่มที่นี่)

ใช้กับ ChatGPT desktop / Codex CLI / Claude Code ซึ่งใช้ MCP config ร่วมกันบนเครื่องเดียวกัน

- **command:** `<path>\spike\.venv\Scripts\python.exe`
- **args:** `<path>\spike\m0_spike.py stdio`

จากนั้นสั่งใน ChatGPT: *"เรียก spike_whoami"* แล้วจดผลลง §7

---

## 6. ขั้นตอนที่ 3 — ต่อ HTTP + tunnel (สำหรับ ChatGPT web)

**หน้าต่างที่ 1:**
```
run-http.cmd
```
มันจะพิมพ์ `local MCP URL: http://127.0.0.1:18765/<token>/mcp` — จด `<token>` ไว้

**หน้าต่างที่ 2:**
```
run-tunnel.cmd
```
(ครั้งแรกติดตั้ง cloudflared: `winget install --id Cloudflare.cloudflared`)
มันจะพิมพ์ URL แบบ `https://xxxx-yyyy.trycloudflare.com`

**URL ที่เอาไปใส่ ChatGPT** = `https://xxxx-yyyy.trycloudflare.com/<token>/mcp`

**ใน ChatGPT web:** Settings → Apps → Advanced → เปิด Developer mode →
Add custom connector → วาง URL → auth = No authentication → บันทึก → เปิดใช้ในแชท

### ⚠️ เรื่อง auth ที่ต้องเข้าใจ

ChatGPT custom connector รองรับแค่ **OAuth** หรือ **No authentication**
spike จึงใส่ secret ไว้ใน path (`/<token>/mcp`) เพื่อไม่ให้ endpoint เปิดโล่งผ่าน tunnel
— URL ที่ผิด token จะได้ 404

**นี่เป็นมาตรการชั่วคราวของ spike เท่านั้น ไม่ใช่ระบบ auth**
PRD §10.6 กำหนดว่า v1 ต้องทำ OAuth จริงใน M7 และถือว่า tunnel URL เป็นความลับ
ไม่ใช่กำแพงป้องกัน

**ปิด tunnel ทันทีเมื่อทดลองเสร็จ** — อย่าเปิดค้างข้ามคืน

---

## 7. การทดลองและตารางบันทึกผล

รันตามลำดับ แล้วเติมช่อง "ผล" ให้ครบ ผลที่ได้จะย้อนกลับไปแก้ PRD §19-20

### OQ-1 — write action ถูกบล็อกบนมือถือไหม (สำคัญที่สุด)

ต่อผ่าน **HTTP + tunnel** (เพราะ stdio ใช้จากมือถือไม่ได้อยู่แล้ว) แล้วสั่งคำสั่งเดียวกัน
จาก 3 ที่ เทียบกัน:

| # | คำสั่งที่พิมพ์ใน ChatGPT | เว็บบนคอม | **แอปมือถือ** | เว็บบนมือถือ |
|---|---|---|---|---|
| E1 | `ใช้ spike_read_file อ่าน hello.txt` | | | |
| E2 | `ใช้ spike_write_file สร้าง e2.txt เนื้อหา "hello"` | | | |
| E3 | `ใช้ spike_overwrite_file เขียนทับ e2.txt เป็น "second"` | | | |

บันทึกเป็น: `สำเร็จ` / `ถูกบล็อก (ข้อความว่า...)` / `ถามยืนยันก่อน` / `error`

**ตีความ**
- E2 และ E3 ถูกบล็อกทั้งคู่บนแอป → ข้อจำกัดอยู่ที่ "การเขียน" ทั้งหมด
- E2 ผ่าน E3 ถูกบล็อก → ข้อจำกัดดูที่ `destructiveHint` → มีผลต่อวิธีติดป้าย tool ใน §8.2
- ผ่านทั้งคู่ → OQ-1 ตกไป ใช้จากมือถือได้เต็มที่

### OQ-2 — รูปภาพ

| # | คำสั่ง | ผล |
|---|---|---|
| E4 | `เรียก spike_return_image` | เห็นภาพ / เห็นแต่ข้อความ / error |

ภาพที่ถูกต้องคือ **แถบสี 6 แถบ (แดง ส้ม เหลือง เขียว ฟ้า ม่วง) ทับด้วยแถบตาหมากรุกขาวดำ**
ถ้าเห็นสี่เหลี่ยมเปล่าหรือ broken image = ส่งได้แต่ render ไม่ได้ ให้บันทึกแยกกัน

**ถ้า E4 ล้มเหลว** → M6 ต้องเปลี่ยนจาก "ส่ง screenshot เข้าแชท" เป็น
"บันทึกไฟล์ + คืน path + ให้ผู้ใช้เปิดดูเอง" ซึ่งลดคุณค่าของ G2 ลงมาก

### OQ-3 — เพดานจำนวน tool

รัน `run-http.cmd --extra-tools N` แล้ว re-sync connector ใน ChatGPT ทุกครั้ง

| N | tool ที่ ChatGPT มองเห็น | อาการผิดปกติ |
|---|---|---|
| 6 (ค่าเริ่มต้น) | | |
| 26 | | |
| 46 | | |
| 86 | | |
| 166 | | |

จดด้วยว่ามี tool หายไปเงียบๆ, error ตอน sync, หรือคำตอบเริ่มช้า/สับสน

### OQ-4 + PRD §11 — session และขนาด output

| # | คำสั่ง | สิ่งที่ต้องจด |
|---|---|---|
| E5 | `เรียก spike_whoami` | protocol version, client name/version, header ที่เห็น |
| E6 | `เรียก spike_echo kilobytes=1` แล้ว 8, 64, 256 | ขนาดที่ยังเข้าครบ / จุดที่เริ่มถูกตัด / error |

**ตีความ E6** → ใช้ตั้งค่า `max_output_bytes` จริงใน PRD §15 (ค่าที่ตั้งไว้ตอนนี้คือเดา 8 KB)

---

## 8. ประตูตัดสินหลังจบ M0

| ผล | ผลต่อแผน |
|---|---|
| OQ-1 บล็อกการเขียนบนแอปมือถือ | ปรับ US6/§7 ให้ชัดว่ามือถือใช้อ่าน+ตรวจ; แนะให้ใช้เว็บบนมือถือ; **ห้ามแก้ด้วยการติดป้าย tool ผิด** (§4) |
| OQ-2 ส่งรูปไม่ได้ | ลดขอบเขต M6; `browser.screenshot` คืน path แทนภาพ |
| OQ-3 เพดานต่ำกว่า 14 tool | ต้องรวบ tool ให้น้อยกว่านี้อีก หรือแยกเป็นหลาย connector |
| OQ-4 OAuth บังคับ/ต้องมี DCR | ขยายขอบเขต M7 ตามที่พบจริง |
| ผ่านหมด | เดินตามแผน §19 ต่อที่ M1 ได้เลย |

เมื่อกรอกตารางครบแล้ว ให้อัปเดต PRD §20 (เปลี่ยน OQ เป็นข้อสรุป) แล้วค่อยเริ่ม M1

---

## 9. ความปลอดภัยระหว่างทำ M0

- spike แตะได้แค่ `spike/spike-sandbox/` — ลบทั้งโฟลเดอร์ได้ตลอดเวลา
- ไม่มี `shell`, ไม่มี tool ลบไฟล์, ไม่มีการออกเน็ตจากฝั่ง server
- ปิด tunnel ทุกครั้งที่เลิกทดลอง และลบ connector ออกจาก ChatGPT เมื่อจบ M0
- `.spike-token` ถูก gitignore ไว้ — ถ้าหลุด ให้ลบไฟล์แล้วรัน `run-http.cmd` ใหม่เพื่อออก token ใหม่
