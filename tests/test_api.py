"""FastAPI 路由測試：以實際測試檔走完 A、B、C 的流程，並檢查錯誤回應格式。"""
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lct_datahub.api.main import create_app

ROOT = Path(__file__).resolve().parent.parent
JV_DIR, JD_DIR, EQE_DIR = ROOT / "JV_test_file", ROOT / "JD_test_file", ROOT / "EQE_test_file"
PNG_MAGIC = b"\x89PNG"


@pytest.fixture
def client(tmp_path) -> TestClient:
    """每個測試用自己的工作資料夾。"""
    return TestClient(create_app(tmp_path))


def _upload(client: TestClient, section: str, paths: list[Path]):
    """上傳檔案並回傳回應。"""
    files = [("files", (p.name, p.read_bytes())) for p in paths]
    return client.post(f"/api/{section}/jobs", files=files)


def _files(folder: Path) -> list[Path]:
    """資料夾內所有檔案（含不接受的副檔名，測試略過機制）。"""
    return sorted(p for p in folder.iterdir() if p.is_file())


needs = lambda folder: pytest.mark.skipif(not folder.exists(), reason=f"沒有 {folder.name}")  # noqa: E731


# ---------- 共用 ----------
def test_health(client):
    """健康檢查。"""
    assert client.get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize("job_id", ["20261106-000000-00000000", "..%5C..%5Cetc", "abc"])
def test_unknown_job_is_404(client, job_id):
    """不存在或格式不符的工作編號（含 ..\\ 路徑穿越）：404。"""
    res = client.get(f"/api/eqe/jobs/{job_id}")
    assert res.status_code == 404 and res.json()["kind"] == "not_found"


def test_upload_rejects_no_valid_files_and_duplicates(client):
    """沒有可處理的檔案、檔名重複：400。"""
    res = client.post("/api/eqe/jobs", files=[("files", ("a.jpg", b"x"))])
    assert res.status_code == 400 and res.json()["kind"] == "input"
    res = client.post("/api/eqe/jobs", files=[("files", ("a.txt", b"x")), ("files", ("a.txt", b"y"))])
    assert res.status_code == 400 and "重複" in res.json()["message"]


def test_bad_file_returns_file_error(client):
    """內容無法辨識：422，附檔名、原因、期望、實際；檔名的路徑部分會被去掉。"""
    res = client.post("/api/eqe/jobs", files=[("files", ("../evil.txt", b"hello\tworld"))])
    body = res.json()
    assert res.status_code == 422 and body["kind"] == "file"
    assert body["filename"] == "evil.txt" and body["reason"] and body["expected"] and body["actual"]


# ---------- C EQE ----------
@needs(EQE_DIR)
def test_eqe_flow(client):
    """上傳 → 改名 → 畫圖 → 下載（兩種儀器打包成 zip）。"""
    res = _upload(client, "eqe", _files(EQE_DIR))
    assert res.status_code == 200
    job = res.json()
    names = [c["name"] for c in job["curves"]]
    assert len(names) == 40 and "S1" in names
    url = f"/api/eqe/jobs/{job['job_id']}"

    # 改名：S1 → X1；GET 也看得到；不合理的改名 400
    renamed = client.put(f"{url}/names", json={"names": {"S1": "X1"}}).json()
    assert "X1" in [c["name"] for c in renamed["curves"]]
    assert client.get(url).json() == renamed
    assert client.put(f"{url}/names", json={"names": {"S1": "  "}}).status_code == 400

    # 畫圖：PNG；名稱不存在或範圍不合理 400
    res = client.post(f"{url}/plots/eqe", json={"names": ["X1", names[-1]], "x_range": [300, 1100]})
    assert res.status_code == 200 and res.content.startswith(PNG_MAGIC)
    assert client.post(f"{url}/plots/rplot", json={"names": ["X1"]}).content.startswith(PNG_MAGIC)
    assert client.post(f"{url}/plots/eqe", json={"names": ["S1"]}).status_code == 400  # 已改名
    assert client.post(f"{url}/plots/eqe", json={"names": ["X1"], "x_range": [900, 300]}).status_code == 400

    # 下載：兩份 Excel 打包成 zip
    res = client.get(f"{url}/excel")
    assert res.headers["content-type"] == "application/zip"
    assert sorted(zipfile.ZipFile(io.BytesIO(res.content)).namelist()) == ["Eqe_Old.xlsx", "Eqe_PD-QE.xlsx"]


# ---------- B 暗電流 ----------
@needs(JD_DIR)
def test_dark_flow(client):
    """上傳 → 面積檢查 → 偏移與指定面積 → 畫圖 → 下載。"""
    job = _upload(client, "dark", _files(JD_DIR)).json()
    url = f"/api/dark/jobs/{job['job_id']}"
    # PD-QE 檔內 4.5 mm²；明志由 |I|/J 反推也是 0.045 cm²，所以一致
    assert len(job["curves"]) == 58 and job["area_report"]["uniform_value"] == 0.045
    assert job["settings"] == {"area": None, "shift_mode": "保持原始", "conditions": None}
    assert not any(c["is_shifted"] for c in job["curves"])

    shifted = client.put(f"{url}/settings", json={"shift_mode": "偏移到 0 V", "area": 0.05}).json()
    assert sum(c["is_shifted"] for c in shifted["curves"]) == 40
    assert {c["area"] for c in shifted["curves"]} == {0.05}
    assert client.put(f"{url}/settings", json={"area": 0}).status_code == 400

    names = [c["name"] for c in shifted["curves"][:3]]
    res = client.post(f"{url}/plots/dark", json={"names": names, "y_range": [1e-10, 1e-2]})
    assert res.content.startswith(PNG_MAGIC)
    assert client.post(f"{url}/plots/dark", json={"names": names, "y_range": [0, 1]}).status_code == 400

    res = client.get(f"{url}/excel")
    assert res.headers["content-type"] == "application/zip"


@needs(JD_DIR)
def test_dark_grouping(client):
    """元件分組：預填 → 確認（須全部分配）；改面積、偏移不會清掉分組。"""
    job = _upload(client, "dark", _files(JD_DIR)).json()
    url = f"/api/dark/jobs/{job['job_id']}"
    devices = job["devices"]
    # 明志的 G1 REF-1_330 K 取開頭代號，與 PD-QE 的 G1-x 同一個元件
    assert "G1" in devices and devices == sorted(devices, key=lambda d: int(d[1:]))
    assert {c["device"] for c in job["curves"] if c["name"].startswith(("G1-", "G1 "))} == {"G1"}

    preview = client.post(f"{url}/grouping/preview", json={"mode": "平均分配", "names": ["A", "B"]}).json()
    assert [c["name"] for c in preview["conditions"]] == ["A", "B"] and preview["unassigned"] == []
    assert sorted(sum((c["samples"] for c in preview["conditions"]), [])) == sorted(devices)

    # 未全部分配：400；全部分配：存檔
    half = {"conditions": [{"name": "A", "samples": devices[:2]}]}
    assert client.put(f"{url}/conditions", json=half).status_code == 400
    saved = client.put(f"{url}/conditions", json={"conditions": preview["conditions"]}).json()
    assert saved["settings"]["conditions"] == preview["conditions"]

    # 改面積與偏移後，分組仍在
    after = client.put(f"{url}/settings", json={"area": 0.05, "shift_mode": "偏移到 0 V"}).json()
    assert after["settings"]["conditions"] == preview["conditions"]


@needs(JD_DIR)
def test_dark_upload_skips_excel_without_abs(client):
    """上傳時 Excel 檔名沒有 _abs 的略過（列在 skipped），其餘照常讀取。"""
    txt = next(p for p in JD_DIR.iterdir() if p.suffix == ".txt")
    files = [("files", (txt.name, txt.read_bytes())), ("files", ("no_mark.xlsx", b"x")), ("files", ("~$t_abs.xlsx", b"x"))]
    job = client.post("/api/dark/jobs", files=files).json()
    assert job["skipped"] == ["no_mark.xlsx", "~$t_abs.xlsx"]
    assert {c["source"] for c in job["curves"]} == {txt.name}
    # 只有不符合規則的檔案：400
    res = client.post("/api/dark/jobs", files=[("files", ("no_mark.xls", b"x"))])
    assert res.status_code == 400 and res.json()["kind"] == "input"


# ---------- A JV ----------
@needs(JV_DIR)
def test_jv_flow(client):
    """上傳 → 分組 → Box 表、篩選、手動保留 → Box 圖、JV 曲線圖 → 下載。"""
    res = _upload(client, "jv", _files(JV_DIR))
    assert res.status_code == 200
    job = res.json()
    url = f"/api/jv/jobs/{job['job_id']}"
    assert len(job["files"]) == 18 and len(job["samples"]) == 9
    assert any(name.endswith(".jpg") for name in job["skipped"])  # 只接受 csv

    # 尚未分組時不能做 Box
    assert client.post(f"{url}/box/table", json={}).status_code == 400

    # 預填：自動每 4 個一組；平均分配名稱不可重複
    preview = client.post(f"{url}/grouping/preview", json={"mode": "自動"}).json()
    assert [len(c["samples"]) for c in preview["conditions"]] == [4, 4, 1] and preview["unassigned"] == []
    bad = client.post(f"{url}/grouping/preview", json={"mode": "平均分配", "names": ["A", "A"]})
    assert bad.status_code == 400

    # 確認分組：有未分配樣品時 400；完整時存檔
    partial = {"conditions": [{"name": "Ref", "samples": job["samples"][:3]}]}
    assert client.put(f"{url}/conditions", json=partial).status_code == 400
    full = {"conditions": [
        {"name": "Ref", "samples": job["samples"][:4]},
        {"name": "0.2%", "samples": job["samples"][4:]},
    ]}
    confirmed = client.put(f"{url}/conditions", json=full).json()
    assert [c["name"] for c in confirmed["settings"]["conditions"]] == ["Ref", "0.2%"]
    assert confirmed["missing"] == []

    # Box 表：範圍篩選與手動保留
    rows = client.post(f"{url}/box/table", json={"mode": "FW"}).json()
    assert rows and all(r["Keep"] for r in rows) and {r["Direction"] for r in rows} == {"FW"}
    filtered = client.post(
        f"{url}/box/table", json={"ranges": {"Efficiency (%)": {"minimum": 1000}}, "keep": {"0": True}},
    ).json()
    assert filtered[0]["Keep"] and not any(r["Keep"] for r in filtered[1:])

    res = client.post(f"{url}/box/plot", json={"param": "Voc (V)", "mode": "FW＋RV"})
    assert res.content.startswith(PNG_MAGIC)
    res = client.post(f"{url}/curves/plot", json={"samples": job["samples"][:2], "directions": ["FW", "RV"]})
    assert res.content.startswith(PNG_MAGIC)

    # 指定面積：Jsc 依比例重算
    before = client.post(f"{url}/box/table", json={}).json()[0]["Jsc (mA/cm^2)"]
    area = confirmed["area_report"]["values"][0]
    client.put(f"{url}/area", json={"area": area * 2})
    after = client.post(f"{url}/box/table", json={}).json()[0]["Jsc (mA/cm^2)"]
    assert after == pytest.approx(before / 2)
    assert client.put(f"{url}/area", json={"area": -1}).status_code == 400

    res = client.get(f"{url}/excel", params={"directions": ["FW", "RV"]})
    assert res.headers["content-type"].startswith("application/vnd.openxmlformats")
