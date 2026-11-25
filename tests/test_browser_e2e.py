"""
REAL-BROWSER end-to-end test: drives the Next.js UI in headless Firefox with Selenium, exactly as a user would
(typing, clicking, waiting for the live results). Verifies the displayed results against independent sources
(the blockchain, the downloaded file's hash).

Requirements:  pip install selenium ;  Firefox + geckodriver (FIREFOX_BIN / GECKODRIVER_BIN env vars if not on PATH)
Services must be running (scripts/start.sh).     Run:  pytest tests/test_browser_e2e.py -v -s

NOT covered: the real MetaMask browser extension (cannot be installed headlessly). The "MetaMask" test uses a
stand-in EIP-1193 provider injected as window.ethereum that forwards to the local Hardhat node (whose accounts are
unlocked). It exercises the app's wallet-connect + viem writeContract + backend confirm flow, not MetaMask itself.
"""
import hashlib, json, os, secrets, shutil, sys, tempfile, time
from pathlib import Path

import pytest, requests

selenium = pytest.importorskip("selenium")
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FRONT = os.environ.get("FRONTEND_URL", "http://localhost:3000")
API = FRONT + "/api"
SHOTS = ROOT / "tests" / "results" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
SUF = secrets.token_hex(3)
DEV, BUY, DEV2 = f"ui_dev_{SUF}", f"ui_buyer_{SUF}", f"ui_dev2_{SUF}"
PW = "Browser-Test-Pass1"
S = {}


@pytest.fixture(scope="module")
def d():
    dl = tempfile.mkdtemp(prefix="dl_")
    S["dl"] = dl
    o = Options(); o.add_argument("-headless")
    o.binary_location = os.environ.get("FIREFOX_BIN", shutil.which("firefox") or "/tmp/mamba/envs/browser/bin/firefox")
    o.set_preference("browser.download.folderList", 2); o.set_preference("browser.download.dir", dl)
    o.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/octet-stream")
    o.set_preference("browser.download.useDownloadDir", True)
    drv = webdriver.Firefox(options=o, service=Service(os.environ.get("GECKODRIVER_BIN", shutil.which("geckodriver") or "/tmp/mamba/envs/browser/bin/geckodriver"), log_output=os.devnull))
    drv.set_window_size(1400, 1000)
    yield drv
    drv.quit(); shutil.rmtree(dl, ignore_errors=True)


def shot(d, name): d.save_screenshot(str(SHOTS / f"{name}.png"))
def X(d, xp, t=60): return WebDriverWait(d, t).until(EC.presence_of_element_located((By.XPATH, xp)))
def gone(d, xp, t=60): return WebDriverWait(d, t).until(EC.invisibility_of_element_located((By.XPATH, xp)))
def click(d, xp, t=60):
    el = WebDriverWait(d, t).until(EC.element_to_be_clickable((By.XPATH, xp)))
    d.execute_script("arguments[0].scrollIntoView({block:'center'})", el); el.click(); return el
def btn(text): return f"//button[normalize-space()='{text}']"
def btn_c(text): return f"//button[contains(normalize-space(), '{text}')]"
def field(d, label, value, t=30):
    el = X(d, f"//label[.//span[contains(normalize-space(), '{label}')]]//input", t)
    el.clear(); el.send_keys(value); return el
def kv(d, key, t=60): return X(d, f"//dt[normalize-space()='{key}']/following-sibling::dd[1]", t)
def text_present(d, txt, t=60): return X(d, f"//*[contains(normalize-space(), '{txt}')]", t)
def go(d, path): d.get(FRONT + path)
def api(method, path, token=None, **kw):
    return requests.request(method, API + path, headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=200, **kw)
def sign_out(d):
    go(d, "/")                                                      # tolerate being logged out already
    time.sleep(1)
    if d.find_elements(By.XPATH, btn("Sign out")):
        click(d, btn("Sign out"))
    X(d, "//h1[contains(., 'Decentralized AI Model Marketplace')]")
def ui_register(d, user, role):
    go(d, "/login"); click(d, btn("Create account"))
    field(d, "Username", user); field(d, "Password", PW)
    Select(X(d, "//label[.//span[normalize-space()='Role']]//select")).select_by_value(role)
    click(d, "//form//button[@type='submit']"); X(d, "//h1[normalize-space()='Dashboard']")
def ui_login(d, user):
    go(d, "/login"); field(d, "Username", user); field(d, "Password", PW)
    click(d, "//form//button[@type='submit']"); X(d, "//h1[normalize-space()='Dashboard']")


# =============================================================== authentication + guards
def test_01_login_guard_and_registration(d):
    go(d, "/"); X(d, "//h1[contains(., 'Decentralized AI Model Marketplace')]")             # unauthenticated -> redirected to /login
    assert d.current_url.endswith("/login")
    go(d, "/train"); X(d, "//h1[contains(., 'Decentralized AI Model Marketplace')]")        # protected page also redirects
    go(d, "/login"); click(d, btn("Create account")); field(d, "Username", "x"); field(d, "Password", "short")
    click(d, "//form//button[@type='submit']"); text_present(d, "username must be 3-32")        # server-side validation shown in the UI
    ui_register(d, DEV, "developer"); shot(d, "01_dashboard_developer")
    X(d, f"//aside//div[normalize-space()='{DEV}']")
    assert "Train Model" in d.page_source and "Cryptographic Protection" in d.page_source   # developer navigation
    sign_out(d)
    go(d, "/login"); field(d, "Username", DEV); field(d, "Password", "wrong-password-1")
    click(d, "//form//button[@type='submit']"); text_present(d, "invalid username or password")
    ui_login(d, DEV)


# =============================================================== phase 1: train
def test_02_train_model_through_the_ui(d):
    go(d, "/train"); click(d, btn("digits"))
    text_present(d, "1797 rows")                                                               # validation report rendered
    X(d, "//span[normalize-space()='PASS']")
    Select(X(d, "//label[.//span[normalize-space()='Algorithm']]//select")).select_by_visible_text("Random Forest")
    field(d, "Trees", "40"); field(d, "Model name", "ui-digits-rf")
    shot(d, "02_train_configured")
    click(d, btn("Train model"))
    X(d, "//h2[contains(., '3 · Training progress')]")
    X(d, "//h2[contains(., '4 · Evaluation')]", 150); shot(d, "03_train_evaluation")
    acc = X(d, "//div[normalize-space()='Accuracy']/following-sibling::div").text
    assert float(acc.strip("%")) >= 90.0, acc
    S["model"] = X(d, "//dt[normalize-space()='Model saved as']/following-sibling::dd//code[1]").text
    assert S["model"].startswith("mdl_")
    st = api("GET", f"/models/{S['model']}/training", api("POST", "/auth/login", json={"username": DEV, "password": PW}).json()["token"]).json()
    assert st["training"]["status"] == "completed" and f"{st['metrics']['accuracy']*100:.2f}%" == acc    # UI shows the REAL stored metric
    S["dev_token"] = api("POST", "/auth/login", json={"username": DEV, "password": PW}).json()["token"]
    assert d.find_elements(By.XPATH, "//table//th[normalize-space()='true ↓ / pred →']")      # confusion matrix rendered
    assert len(d.find_elements(By.XPATH, "//h2[contains(., 'Evaluation')]/ancestor::section[1]//table")) >= 2    # + per-class table


# =============================================================== phase 2: deploy + predict
def test_03_deploy_and_predict(d):
    go(d, "/deploy")
    click(d, btn("Deploy model"))
    X(d, "//dt[normalize-space()='Is the exact trained artifact']/following-sibling::dd//span[normalize-space()='PASS']")
    shot(d, "04_deployed")
    sample = click(d, btn_c("Test-set sample 1"))
    true_label = sample.text.split("true: ")[1].strip(")")
    click(d, btn("Predict"))
    pred = X(d, "//*[contains(., 'Prediction:')]/span[contains(@class,'text-2xl')]").text
    assert pred == true_label, (pred, true_label)
    shot(d, "05_prediction")


# =============================================================== phase 3: crypto protection
def test_04_cryptographic_protection(d):
    go(d, "/protect")
    field(d, "Account password", PW)
    click(d, btn("Run all 4 steps"))
    X(d, "//*[contains(., 'cryptographically protected and its artifacts are now immutable')]", 120); shot(d, "06_protected")
    root = kv(d, "Merkle root").text
    sha = kv(d, "SHA3-256 (original)").text
    assert len(root) == 64 and len(sha) == 64
    doc = api("GET", f"/models/{S['model']}/crypto", S["dev_token"]).json()["crypto"]
    assert doc["merkle"]["root"] == root and doc["original_sha3"] == sha                      # UI == backend
    assert kv(d, "Algorithm").text.startswith("ECDSA P-256")
    X(d, "//*[contains(., 'Plaintext artifact securely deleted')]")
    assert len(d.find_elements(By.XPATH, "//span[normalize-space()='completed']")) >= 4          # all 4 step cards completed
    # Merkle chunk verification via the UI
    n = int(kv(d, "Chunks").text.split(" ")[0])
    field(d, "Chunk index", str(n - 1)); click(d, btn("Verify chunk"))
    X(d, "//*[contains(., 'valid against stored root')]/span[normalize-space()='PASS']")
    S["root"], S["sha"] = root, sha


# =============================================================== phase 4: blockchain registration (custodial)
def test_05_register_on_blockchain(d):
    go(d, "/registry")
    field(d, "Account password", PW)
    click(d, btn("Register with my developer wallet"))
    txh = kv(d, "Transaction hash", 90).text; shot(d, "07_registered")
    assert txh.startswith("0x") and len(txh) == 66
    # independent verification against the chain
    from web3 import Web3
    dep = json.loads((ROOT / "blockchain" / "deployment.json").read_text())
    w3 = Web3(Web3.HTTPProvider(dep["rpcUrl"]))
    rc = w3.eth.get_transaction_receipt(txh); assert rc.status == 1 and str(rc.blockNumber) == kv(d, "Block number").text
    # the page also reads the record DIRECTLY from the chain in the browser (wagmi + viem), bypassing the backend
    X(d, "//dt[normalize-space()='Original hash (SHA3-256)']/following-sibling::dd//span[normalize-space()='PASS']", 60)
    X(d, "//dt[normalize-space()='Merkle root']/following-sibling::dd//span[normalize-space()='PASS']")
    assert S["root"] in d.page_source and S["sha"] in d.page_source
    S["tx"] = txh


# =============================================================== phase 5: buyer flow
def test_06_buyer_verifies_requests_and_downloads(d):
    sign_out(d); ui_register(d, BUY, "buyer"); shot(d, "08_dashboard_buyer")
    assert "Train Model" not in d.page_source                                                  # buyers have no developer nav
    go(d, "/marketplace"); X(d, "//div[normalize-space()='ui-digits-rf']")
    shot(d, "09_marketplace")
    click(d, f"//div[normalize-space()='ui-digits-rf']/ancestor::section//a[contains(., 'View details')]")
    X(d, "//h1[contains(., 'ui-digits-rf')]")
    assert S["tx"] in d.page_source                                                            # blockchain transaction reference shown
    click(d, btn("Run verification"))
    X(d, "//h2[contains(., 'Verify the blockchain record')]/ancestor::section//span[normalize-space()='PASS']", 60)
    text_present(d, "8 passed, 0 failed"); shot(d, "10_buyer_verification")
    # unauthorised state: no download controls before access is granted
    assert not d.find_elements(By.XPATH, btn("Verify & decrypt securely"))
    click(d, btn_c("Request access"))
    X(d, "//span[normalize-space()='approved']")
    field(d, "Your account password", "wrong-password-xx"); click(d, btn("Verify & decrypt securely"))
    text_present(d, "wrong password")                                                          # key not released for a wrong password
    assert not d.find_elements(By.XPATH, btn("Download model"))
    field(d, "Your account password", PW); click(d, btn("Verify & decrypt securely"))
    X(d, "//h2[contains(., 'Authorization report')]/following::span[normalize-space()='AUTHORIZED']", 90); shot(d, "11_authorization_report")
    for step in ["access grant", "buyer certificate", "developer certificate", "retrieve encrypted", "blockchain record", "integrity verification", "key exchange", "decrypt", "plaintext hash", "release"]:
        assert step in d.page_source, step
    plain = X(d, "//*[contains(., 'equals the on-chain original hash')]/code").text
    click(d, btn_c("Download model")); X(d, "//*[contains(., 'Saved ')]", 60)
    files = []
    for _ in range(40):
        files = [f for f in os.listdir(S["dl"]) if f.endswith(".joblib")]
        if files: break
        time.sleep(0.5)
    assert files, "browser did not save the downloaded model"
    data = Path(S["dl"], files[0]).read_bytes()
    from web3 import Web3
    dep = json.loads((ROOT / "blockchain" / "deployment.json").read_text()); abi = json.loads((ROOT / "blockchain" / "artifacts-custom" / "ModelRegistry.json").read_text())["abi"]
    rec = Web3(Web3.HTTPProvider(dep["rpcUrl"])).eth.contract(address=dep["address"], abi=abi).functions.getRecord(S["model"]).call()
    assert "0x" + hashlib.sha3_256(data).hexdigest() == "0x" + bytes(rec[3]).hex() == plain   # downloaded bytes == on-chain original hash
    # the ENCRYPTED artifact can be fetched by anyone; its hash must equal the on-chain encrypted hash
    click(d, btn("Download encrypted artifact (ciphertext only)")); X(d, "//*[contains(., 'Saved encrypted artifact')]", 60)
    enc_files = []
    for _ in range(40):
        enc_files = [f for f in os.listdir(S["dl"]) if f.endswith(".enc")]
        if enc_files: break
        time.sleep(0.5)
    assert enc_files, "browser did not save the encrypted artifact"
    assert "0x" + hashlib.sha3_256(Path(S["dl"], enc_files[0]).read_bytes()).hexdigest() == "0x" + bytes(rec[4]).hex()   # == on-chain encryptedHash
    assert Path(S["dl"], enc_files[0]).read_bytes()[:8] == b"AIMKTGCM"
    # inference through the distributed copy, in the UI
    sch = api("GET", f"/models/{S['model']}/schema", S["dev_token"]).json()
    row = sch["sample_inputs"][2]
    ta = X(d, "//textarea"); ta.clear(); ta.send_keys(json.dumps([row["inputs"]]))
    click(d, btn("Predict"))
    assert X(d, "//*[starts-with(normalize-space(), 'Prediction:')]/b").text == row["true_label"]
    text_present(d, "hash-verified against blockchain")
    # single-use license is now exhausted
    d.refresh(); X(d, "//span[normalize-space()='exhausted']"); shot(d, "12_license_exhausted")
    assert not d.find_elements(By.XPATH, btn("Verify & decrypt securely"))


# =============================================================== phase 6: security suite (developer)
def test_07_security_suite_in_the_ui(d):
    sign_out(d); ui_login(d, DEV)
    go(d, "/security")
    Select(X(d, "//select")).select_by_value(S["model"])
    click(d, btn("Verify now")); text_present(d, "8 passed"); X(d, "//h2[contains(., 'Integrity')]/ancestor::section//span[normalize-space()='PASS']")
    field(d, "Your password", PW)
    click(d, btn("Run all 6 tests"))
    WebDriverWait(d, 240).until(lambda x: len(x.find_elements(By.XPATH, "//span[normalize-space()='as expected']")) == 6)
    shot(d, "13_security_suite")
    assert "UNEXPECTED" not in d.page_source
    for needle in ["Not an authorized developer", "Not the model owner", "Model already registered", "InvalidTag", "failed tx"]:
        assert needle in d.page_source, needle
    # each test card shows the ACTUAL outcome next to the EXPECTED one
    cards = d.find_elements(By.XPATH, "//div[contains(@class,'rounded-lg border p-4')][.//span[normalize-space()='as expected']]")
    actual = [c.find_elements(By.XPATH, ".//span[normalize-space()='as expected']/preceding-sibling::span[1]")[0].text for c in cards]
    assert actual == ["PASS", "FAIL", "FAIL", "REJECTED", "REJECTED", "DENIED"], actual
    assert api("POST", f"/models/{S['model']}/verify", S["dev_token"]).json()["status"] == "PASS"   # model intact after the attacks
    logs = api("GET", f"/security/logs?model_id={S['model']}", S["dev_token"]).json()
    assert sum(l["kind"] == "tamper_test" for l in logs) >= 6


# =============================================================== dashboard reflects reality
def test_08_dashboard_numbers_match_backend(d):
    go(d, "/")
    X(d, "//div[normalize-space()='Blockchain-registered']/following-sibling::div")
    time.sleep(1.5)
    stats = api("GET", "/dashboard/stats", S["dev_token"]).json()
    shown = lambda label: d.find_element(By.XPATH, f"//div[normalize-space()='{label}']/following-sibling::div").text
    assert shown("Blockchain-registered") == str(stats["models_registered"]) and shown("Deployed") == str(stats["models_deployed"])
    assert shown("Tamper tests as expected") == f"{stats['tamper_tests_as_expected']}/{stats['tamper_tests_run']}"
    shot(d, "14_dashboard_final")


# =============================================================== wallet path (stand-in provider)
STANDIN = """
const ACCOUNT = arguments[0];
const rpc = async (m, p) => (await (await fetch('http://127.0.0.1:8545', {method:'POST', headers:{'content-type':'application/json'},
   body: JSON.stringify({jsonrpc:'2.0', id:1, method:m, params:p||[]})})).json());
window.__ethCalls = [];
window.ethereum = { isMetaMask: true, isStandIn: true,
  request: async ({method, params}) => {
    window.__ethCalls.push(method);
    if (method === 'eth_requestAccounts' || method === 'eth_accounts') return [ACCOUNT];
    if (method === 'eth_chainId') return '0x7a69';
    if (method === 'wallet_switchEthereumChain' || method === 'wallet_addEthereumChain') return null;
    const r = await rpc(method, params);
    if (r.error) { const e = new Error(r.error.message); e.code = r.error.code; throw e; }
    return r.result;
  }, on(){}, removeListener(){} };
"""

def test_09_register_with_wallet_standin(d):
    from eth_account import Account
    sign_out(d)
    assert api("POST", "/auth/register", json={"username": DEV2, "password": PW, "role": "developer"}).status_code == 201
    t2 = api("POST", "/auth/login", json={"username": DEV2, "password": PW}).json()["token"]
    ds = api("POST", "/datasets/samples/wine/use", t2).json()["id"]
    mid = api("POST", "/models/train", t2, json={"dataset_id": ds, "algorithm": "logistic_regression", "name": "ui-wine"}).json()["id"]
    for _ in range(120):
        if api("GET", f"/models/{mid}/training", t2).json()["training"]["status"] != "running": break
        time.sleep(0.5)
    assert api("POST", f"/models/{mid}/deploy", t2).status_code == 200
    assert api("POST", f"/models/{mid}/protect", t2, json={"password": PW}).status_code == 200
    ui_login(d, DEV2)
    d.execute_script("localStorage.setItem('aimkt.activeModel', arguments[0])", mid)
    go(d, "/registry")
    acct = "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc"                                         # an unlocked Hardhat account (stand-in for the MetaMask account)
    d.execute_script(STANDIN, acct)
    click(d, btn("Connect MetaMask"))
    X(d, f"//header//span[contains(., '{acct[:6]}')]")
    X(d, "//dt[normalize-space()='MetaMask']/following-sibling::dd//span[normalize-space()='PASS']")   # chain id check passes
    click(d, btn("Register with MetaMask"))
    X(d, "//dt[normalize-space()='Transaction hash']", 90); shot(d, "15_registered_via_wallet")
    assert "MetaMask / external wallet" in d.page_source
    calls = d.execute_script("return window.__ethCalls")
    assert "eth_sendTransaction" in calls and "eth_requestAccounts" in calls
    m = api("GET", f"/models/{mid}", t2).json()
    assert m["status"] == "registered" and m["blockchain"]["creator"].lower() == acct.lower()
    assert api("POST", f"/models/{mid}/verify", t2).json()["status"] == "PASS"                  # verifies with owner = external wallet


# =============================================================== CSV upload through the UI (valid + invalid)
def train_params_iris_lr(d):
    Select(X(d, "//label[.//span[normalize-space()='Algorithm']]//select")).select_by_visible_text("Logistic Regression")


def test_10_csv_upload_in_the_ui(d):
    sign_out(d); ui_login(d, DEV)
    iris = Path(S["dl"], "my_iris.csv"); iris.write_bytes((ROOT / "datasets" / "iris.csv").read_bytes())
    bad = Path(S["dl"], "too_small.csv"); bad.write_text("a,b,y\n1,2,x\n3,4,y\n")
    go(d, "/train")
    X(d, "//input[@type='file']").send_keys(str(bad))
    click(d, btn("Upload & validate"))
    text_present(d, "Need at least 30 rows"); shot(d, "16_invalid_csv_rejected")
    assert d.find_element(By.XPATH, btn("Train model")).get_attribute("disabled") is not None         # cannot train on an invalid dataset
    X(d, "//input[@type='file']").send_keys(str(iris))
    click(d, btn("Upload & validate"))
    text_present(d, "150 rows × 5 columns")
    X(d, "//span[normalize-space()='PASS']")
    assert d.find_element(By.XPATH, btn("Train model")).get_attribute("disabled") is None
    train_params_iris_lr(d); field(d, "Model name", "ui-iris-upload")
    click(d, btn("Train model")); X(d, "//h2[contains(., '4 · Evaluation')]", 120)
    acc = float(X(d, "//div[normalize-space()='Accuracy']/following-sibling::div").text.strip("%"))
    assert acc >= 85.0, acc
    S["m_undeploy"] = X(d, "//dt[normalize-space()='Model saved as']/following-sibling::dd//code[1]").text
    ds = api("GET", "/datasets", S["dev_token"]).json()
    assert any(x["filename"] == "my_iris.csv" and x["source"] == "upload" and x["validation"]["valid"] for x in ds)
    assert any(x["filename"] == "too_small.csv" and not x["validation"]["valid"] for x in ds)


# =============================================================== deploy / undeploy / redeploy in the UI
def test_11_undeploy_and_redeploy_in_the_ui(d):
    go(d, "/deploy")                                                      # the model trained in test_10 is the active model
    click(d, btn("Deploy model"))
    X(d, "//dt[normalize-space()='Is the exact trained artifact']/following-sibling::dd//span[normalize-space()='PASS']")
    click(d, btn("Undeploy"))
    X(d, "//dt[normalize-space()='Status']/following-sibling::dd[normalize-space()='undeployed']")
    X(d, "//h2[contains(., 'Deployment')]/following::span[normalize-space()='undeployed']")
    assert not d.find_elements(By.XPATH, "//h2[contains(., 'Test predictions')]")                      # inference card is gone
    assert api("POST", f"/models/{S['m_undeploy']}/predict", S["dev_token"], json={"inputs": [[1, 2, 3, 4]]}).status_code == 409
    shot(d, "17_undeployed")
    click(d, btn("Deploy model"))
    X(d, "//h2[contains(., 'Test predictions')]")
    sample = click(d, btn_c("Test-set sample 1")); true_label = sample.text.split("true: ")[1].strip(")")
    click(d, btn("Predict"))
    assert X(d, "//*[contains(., 'Prediction:')]/span[contains(@class,'text-2xl')]").text == true_label


# =============================================================== step-by-step protection + approval-required license (UI, both roles)
def test_12_stepwise_protection_registration_and_approval_flow(d):
    # developer: a deployed model prepared quickly through the API; everything after that is done in the UI
    ds = api("POST", "/datasets/samples/iris/use", S["dev_token"]).json()["id"]
    mid = api("POST", "/models/train", S["dev_token"], json={"dataset_id": ds, "algorithm": "random_forest", "name": "ui-approval-model"}).json()["id"]
    for _ in range(120):
        if api("GET", f"/models/{mid}/training", S["dev_token"]).json()["training"]["status"] != "running": break
        time.sleep(0.5)
    assert api("POST", f"/models/{mid}/deploy", S["dev_token"]).status_code == 200
    S["m_approval"] = mid
    d.execute_script("localStorage.setItem('aimkt.activeModel', arguments[0])", mid)
    go(d, "/protect")
    Select(X(d, "//label[.//span[contains(normalize-space(), 'License')]]//select")).select_by_value("approval-required")
    for _ in range(40):                                                    # the UI persisted the choice server-side
        if api("GET", f"/models/{mid}", S["dev_token"]).json()["license"] == "approval-required": break
        time.sleep(0.25)
    assert api("GET", f"/models/{mid}", S["dev_token"]).json()["license"] == "approval-required"
    # steps are ordered: later steps stay disabled until the earlier ones are done
    for later in ("Encrypt", "Build Merkle tree", "Verify certificate & sign"):
        assert d.find_element(By.XPATH, btn(later)).get_attribute("disabled") is not None, later
    click(d, btn("Compute hash")); kv(d, "SHA3-256 (original)")
    assert d.find_element(By.XPATH, btn("Build Merkle tree")).get_attribute("disabled") is not None     # still needs encryption
    click(d, btn("Encrypt")); kv(d, "SHA3-256 (encrypted)")
    click(d, btn("Build Merkle tree")); kv(d, "Merkle root")
    assert d.find_element(By.XPATH, btn("Verify certificate & sign")).get_attribute("disabled") is not None  # needs the password
    field(d, "Account password", PW)
    click(d, btn("Verify certificate & sign"))
    X(d, "//*[contains(., 'cryptographically protected and its artifacts are now immutable')]", 60)
    assert d.find_element(By.XPATH, btn("Compute hash")).get_attribute("disabled") is not None          # immutable once signed
    go(d, "/registry"); field(d, "Account password", PW)
    click(d, btn("Register with my developer wallet")); kv(d, "Transaction hash", 90)
    assert api("GET", f"/models/{mid}", S["dev_token"]).json()["status"] == "registered"

    # two buyers request access in the UI
    B2, B3 = f"ui_buyer2_{SUF}", f"ui_buyer3_{SUF}"
    for u in (B2, B3):
        assert api("POST", "/auth/register", json={"username": u, "password": PW, "role": "buyer"}).status_code == 201
        sign_out(d); ui_login(d, u)
        go(d, f"/marketplace/{mid}")
        click(d, btn("Request access (approval-required)"))
        text_present(d, "Waiting for the developer to approve")
        assert not d.find_elements(By.XPATH, btn("Verify & decrypt securely"))                          # no key flow while pending
    shot(d, "18_request_pending")
    # the developer approves one and denies the other, in the UI
    sign_out(d); ui_login(d, DEV); go(d, "/marketplace")
    X(d, "//h2[contains(., 'Access requests for my models')]")
    click(d, f"//tr[.//td[normalize-space()='{B2}']]//button[normalize-space()='Approve']")
    X(d, f"//tr[.//td[normalize-space()='{B2}']]//span[normalize-space()='approved']")
    click(d, f"//tr[.//td[normalize-space()='{B3}']]//button[normalize-space()='Deny']")
    X(d, f"//tr[.//td[normalize-space()='{B3}']]//span[normalize-space()='denied']"); shot(d, "19_developer_decisions")
    # approved buyer can now verify + decrypt (3 downloads allowed), denied buyer cannot
    sign_out(d); ui_login(d, B2); go(d, f"/marketplace/{mid}")
    text_present(d, "downloads 0/3")
    field(d, "Your account password", PW); click(d, btn("Verify & decrypt securely"))
    X(d, "//h2[contains(., 'Authorization report')]/following::span[normalize-space()='AUTHORIZED']", 90)
    assert "retrieve encrypted" in d.page_source
    d.refresh(); text_present(d, "downloads 1/3")
    sign_out(d); ui_login(d, B3); go(d, f"/marketplace/{mid}")
    X(d, "//span[normalize-space()='denied']")
    assert not d.find_elements(By.XPATH, btn("Verify & decrypt securely")) and d.find_elements(By.XPATH, btn_c("Request access"))
    shot(d, "20_denied_buyer")
