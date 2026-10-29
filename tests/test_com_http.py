"""WinHttp.WinHttpRequest.5.1 / MSXML2.XMLHTTP emulation against a local HTTP server (no internet needed)."""
import http.server
import os
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = ("got " + self.path + " ua=" + ("WinHttp" in self.headers.get("User-Agent", "")).__str__()).encode()
        self.send_response(200 if self.path != "/missing" else 404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("X-Test", "bunny")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(n).decode()
        self.send_response(201)
        self.end_headers()
        self.wfile.write(("posted " + data + " type=" + self.headers.get("Content-Type", "")).encode())


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    script = f'''
out(s) => FileAppend(s "`n", "*")
base := "http://127.0.0.1:{port}"
w := ComObject("WinHttp.WinHttpRequest.5.1")
w.Open("GET", base "/hello", false)
w.Send()
out(w.Status " " w.ResponseText " " w.GetResponseHeader("X-Test") " " w.ResponseBody.MaxIndex())
w.Open("POST", base "/api", false)
w.SetRequestHeader("Content-Type", "application/json")
w.Send('{{"a":1}}')
out(w.Status " " w.ResponseText)
w.Open("GET", base "/missing", false), w.Send()
out(w.Status " " w.StatusText)
a := ComObject("WinHttp.WinHttpRequest.5.1")
done := ""
class Sink {{
    OnResponseFinished(req) {{
        global done
        done := "finished"
    }}
}}
ComObjConnect(a, Sink())
a.Open("GET", base "/async", true), a.Send()
a.WaitForResponse()
Sleep 100
out("async " a.ResponseText " " done)
x := ComObject("MSXML2.XMLHTTP")
x.open("GET", base "/xml", false), x.send()
out("xmlhttp " x.readyState " " x.status " " x.responseText)
try {{
    b := ComObject("WinHttp.WinHttpRequest.5.1")
    b.Open("GET", "http://nonexistent.invalid/", false), b.Send()
}} catch OSError as e
    out("dns " (InStr(e.Message, "80072EE7") > 0))
'''
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "http_test.ahk")
    open(path, "w").write(script)
    r = subprocess.run([sys.executable, "-m", "bunnyhotkey", "--console", "--backend=null", path], cwd=ROOT,
                       capture_output=True, text=True, timeout=60)
    os.remove(path)
    want = ("200 got /hello ua=True bunny 17\n201 posted {\"a\":1} type=application/json\n404 Not Found\n"
            "async got /async ua=True finished\nxmlhttp 4 200 got /xml ua=True\ndns 1\n")
    if r.stdout + r.stderr != want:
        print("FAIL\n" + r.stdout + r.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
