"""
CT Table Decryptor
选择文件 → 点击解密 → 弹窗进度条 → 导出
"""
import os, sys, zlib, re, base64, json, threading, time

# 核心

def _try_decompress(data: bytearray, offset: int, label: str) -> bytes:
    compressed = bytes(data[offset:])
    for wbits in [15, -15, 15 + 16]:
        try:
            result = zlib.decompress(compressed, wbits)
            if len(result) >= 4:
                size = int.from_bytes(result[:4], 'little', signed=False)
                if 0 < size <= len(result) * 100:
                    actual = result[4:4 + size]
                    if actual[:5] == b'<?xml':
                        return actual
            return result
        except (zlib.error, Exception):
            continue
    raise RuntimeError(f"Decompress failed ({label})")

def clean_ct_xml(xml: str) -> str:
    lines = xml.split('\n')
    kept = []
    in_forms = False
    for line in lines:
        if '<Forms>' in line:
            in_forms = True
            continue
        if '</Forms>' in line:
            in_forms = False
            continue
        if not in_forms:
            kept.append(line)
    xml = '\n'.join(kept)
    m = re.search(r'<LuaScript>.*?</LuaScript>', xml, re.DOTALL)
    if m and 'createForm' in m.group(0):
        xml = xml.replace(m.group(0), '')
    return xml


# webview API

class Api:
    def __init__(self):
        self._window = None
        self.clean_forms = True
        self._pending_name = ""
        self._pending_data: bytearray | None = None
        self.last_result: bytes | None = None
        self.last_name = ""

    def set_window(self, w):
        self._window = w

    # 文件选择

    def open_file(self):
        result = self._window.create_file_dialog(
            dialog_type=webview.OPEN_DIALOG,
            file_types=['Cheat Table (*.ct;*.CETRAINER)', 'All files (*.*)'],
        )
        if result:
            path = result[0]
            name = os.path.basename(path)
            try:
                with open(path, 'rb') as f:
                    data = bytearray(f.read())
                self._pending_name = name
                self._pending_data = data
                self.js(f'onFileSelected({json.dumps(name)},{len(data)})')
            except Exception as e:
                self.js(f'onFileError({json.dumps(str(e))})')

    def process_data(self, name: str, b64: str):
        raw = base64.b64decode(b64)
        self._pending_name = name
        self._pending_data = bytearray(raw)
        self.js(f'onFileSelected({json.dumps(name)},{len(raw)})')

    # 执行解密

    def start_decrypt(self):
        if self._pending_data is None:
            return
        data = bytearray(self._pending_data)
        name = self._pending_name
        n = len(data)

        def task():
            try:
                # 1. 读取完成
                self.js('onDecryptProgress(8, "准备数据")')
                time.sleep(0.05)

                # 2. 正向 XOR
                for i in range(2, n):
                    data[i] ^= data[i - 2]
                self.js('onDecryptProgress(28, "XOR 解密 (1/3)")')
                time.sleep(0.03)

                # 3. 反向 XOR
                for i in range(n - 2, -1, -1):
                    data[i] ^= data[i + 1]
                self.js('onDecryptProgress(48, "XOR 解密 (2/3)")')
                time.sleep(0.03)

                # 4. 密钥 XOR
                k = 0xCE
                for i in range(n):
                    data[i] ^= (k & 0xFF)
                    k += 1
                self.js('onDecryptProgress(65, "XOR 解密 (3/3)")')
                time.sleep(0.03)

                # 5. 解压缩
                dec = _try_decompress(
                    data, 5, "new"
                ) if bytes(data[:5]) == b"CHEAT" else _try_decompress(
                    data, 0, "old"
                )
                self.js('onDecryptProgress(82, "解压缩完成")')
                time.sleep(0.05)

                # 6. 清理表单
                xml = dec.decode('utf-8', errors='replace')
                before = len(xml)
                cleaned = clean_ct_xml(xml) if self.clean_forms else xml
                after = len(cleaned)

                self.last_result = cleaned.encode('utf-8')
                base_name, _ = os.path.splitext(name)
                self.last_name = base_name + "_clean.ct"

                self.js('onDecryptProgress(100, "解密完成")')
                time.sleep(0.1)
                self.js(f'onDecryptComplete({json.dumps(name)},{before},{after})')
            except Exception as e:
                self.js(f'onDecryptError({json.dumps(str(e))})')

        threading.Thread(target=task, daemon=True).start()

    def set_clean_forms(self, on):
        if isinstance(on, str):
            on = on.lower() in ('true', '1')
        self.clean_forms = bool(on)

    def export_file(self) -> str:
        if not self.last_result:
            return json.dumps({'ok': False})
        out = self._window.create_file_dialog(
            dialog_type=webview.SAVE_DIALOG,
            save_filename=self.last_name,
            file_types=['Cheat Table (*.ct)'],
        )
        if not out:
            return json.dumps({'ok': False})
        with open(out, 'wb') as f:
            f.write(self.last_result)
        return json.dumps({'ok': True, 'path': out})

    def js(self, code: str):
        if self._window:
            try:
                self._window.evaluate_js(code)
            except Exception:
                pass


# 入口

if __name__ == "__main__":
    import webview

    if getattr(sys, 'frozen', False) or '__compiled__' in globals():
        base_dir = os.path.dirname(os.path.abspath(__file__))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(base_dir, 'index.html')

    api = Api()
    window = webview.create_window(
        title='CT Decryptor',
        url=html_path,
        js_api=api,
        width=640,
        height=600,
        resizable=True,
        min_size=(520, 480),
    )
    api.set_window(window)
    webview.start()
