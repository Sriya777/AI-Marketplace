"""
chain.py - the backend's only gateway to the blockchain (web3.py -> ModelRegistry on the local
Hardhat chain). Every method performs REAL JSON-RPC calls / transactions; nothing is simulated.

The blockchain is the authoritative source of integrity + ownership records. This module never
caches a record: get_record() always reads from the chain.
"""
import json
import re
import threading
from typing import Optional

from eth_account import Account
from web3 import Web3

from . import config

_lock = threading.RLock()       # serialises nonce allocation for our own accounts
_state = {}


class ChainError(Exception):
    pass


class ChainRevert(ChainError):
    """The EVM executed the call and the contract reverted it."""
    def __init__(self, reason, tx_hash=None):
        super().__init__(reason)
        self.reason, self.tx_hash = reason, tx_hash


_REASON_RE = re.compile(r"reason string '([^']*)'")
_REVERT_RE = re.compile(r"execution reverted:? ?(?:Error: )?(.*)")
_TXHASH_RE = re.compile(r"'txHash': '(0x[0-9a-fA-F]{64})'")


def _reason(exc) -> str:
    s = str(exc)
    m = _REASON_RE.search(s)
    if m:
        return m.group(1)
    m = _REVERT_RE.search(s)
    return (m.group(1) if m else s)[:200]


def _txhash_from_exc(exc) -> Optional[str]:
    m = _TXHASH_RE.search(str(exc))
    return m.group(1) if m else None


def _connect():
    if _state.get("ok"):
        return
    with _lock:
        if _state.get("ok"):
            return
        if not config.DEPLOYMENT_FILE.exists() or not config.ARTIFACT_FILE.exists():
            raise ChainError("contract not deployed: run `node scripts/compile.js && node scripts/deploy_raw.js` in blockchain/")
        deployment = json.loads(config.DEPLOYMENT_FILE.read_text())
        artifact = json.loads(config.ARTIFACT_FILE.read_text())
        w3 = Web3(Web3.HTTPProvider(config.CHAIN_RPC_URL, request_kwargs={"timeout": 30}))
        if not w3.is_connected():
            raise ChainError(f"no blockchain node reachable at {config.CHAIN_RPC_URL} (start `npx hardhat node`)")
        if not w3.eth.get_code(Web3.to_checksum_address(deployment["address"])):
            raise ChainError("no contract code at the deployed address - the chain was reset; "
                             "re-run `node scripts/deploy_raw.js`")
        _state.update(
            w3=w3, abi=artifact["abi"], deployment=deployment,
            contract=w3.eth.contract(address=Web3.to_checksum_address(deployment["address"]), abi=artifact["abi"]),
            admin=Account.from_key(config.CHAIN_ADMIN_PRIVATE_KEY), ok=True)


def reset():
    _state.clear()


def is_available() -> bool:
    try:
        _connect(); return True
    except Exception:
        _state.clear(); return False


def w3() -> Web3:
    _connect(); return _state["w3"]


def contract():
    _connect(); return _state["contract"]


def config_for_frontend() -> dict:
    _connect()
    return {"address": _state["deployment"]["address"], "chainId": _state["w3"].eth.chain_id,
            "rpcUrl": config.CHAIN_RPC_URL, "abi": _state["abi"]}


def status() -> dict:
    try:
        _connect()
    except Exception as e:
        return {"connected": False, "error": str(e)}
    web3 = _state["w3"]
    c = _state["contract"]
    return {"connected": True, "rpcUrl": config.CHAIN_RPC_URL, "chainId": web3.eth.chain_id,
            "blockNumber": web3.eth.block_number, "contractAddress": _state["deployment"]["address"],
            "deployedAtBlock": _state["deployment"].get("blockNumber"),
            "adminAddress": c.functions.admin().call(), "modelCount": c.functions.modelCount().call()}


# ------------------------------------------------------------------ transactions
def new_wallet():
    acct = Account.create()
    return acct.address, acct.key.hex() if acct.key.hex().startswith("0x") else "0x" + acct.key.hex()


def address_of(private_key_hex: str) -> str:
    return Account.from_key(private_key_hex).address


def _send(account, fn, gas=None):
    """Build, sign and send a contract call from `account`. Raises ChainRevert on revert."""
    _connect()
    web3 = _state["w3"]
    with _lock:
        tx = fn.build_transaction({"from": account.address, "chainId": web3.eth.chain_id,
                                   "nonce": web3.eth.get_transaction_count(account.address, "pending"),
                                   **({"gas": gas} if gas else {})}) if gas else None
        if tx is None:
            try:
                est = fn.estimate_gas({"from": account.address})
            except Exception as e:
                raise ChainRevert(_reason(e))
            tx = fn.build_transaction({"from": account.address, "chainId": web3.eth.chain_id,
                                       "nonce": web3.eth.get_transaction_count(account.address, "pending"),
                                       "gas": int(est * 1.25) + 10000})
        signed = account.sign_transaction(tx)
        try:
            tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
        except Exception as e:
            raise ChainRevert(_reason(e), _txhash_from_exc(e))
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    if receipt.status != 1:
        raise ChainRevert("transaction reverted", tx_hash.hex())
    block = web3.eth.get_block(receipt.blockNumber)
    h = tx_hash.hex()
    return {"txHash": h if h.startswith("0x") else "0x" + h, "blockNumber": receipt.blockNumber,
            "blockTimestamp": block["timestamp"], "gasUsed": receipt.gasUsed, "from": account.address}


def authorize_developer(address: str) -> Optional[dict]:
    """Admin authorizes a wallet to register models. No-op if already authorized."""
    c = contract()
    address = Web3.to_checksum_address(address)
    if c.functions.authorizedDevelopers(address).call():
        return None
    return _send(_state["admin"], c.functions.authorizeDeveloper(address))


def is_authorized(address: str) -> bool:
    return contract().functions.authorizedDevelopers(Web3.to_checksum_address(address)).call()


def fund(address: str, eth: float = None) -> Optional[dict]:
    """Local-chain convenience: top up a wallet with test ETH from the admin account."""
    if not config.AUTO_FUND_WALLETS:
        return None
    web3 = w3()
    address = Web3.to_checksum_address(address)
    target = web3.to_wei(eth if eth is not None else config.FUND_AMOUNT_ETH, "ether")
    if web3.eth.get_balance(address) >= target // 2:
        return None
    admin = _state["admin"]
    with _lock:
        tx = {"to": address, "value": target, "gas": 21000, "chainId": web3.eth.chain_id,
              "nonce": web3.eth.get_transaction_count(admin.address, "pending"),
              "maxFeePerGas": web3.eth.gas_price * 2, "maxPriorityFeePerGas": 1}
        h = web3.eth.send_raw_transaction(admin.sign_transaction(tx).raw_transaction)
    web3.eth.wait_for_transaction_receipt(h, timeout=60)
    return {"funded": address, "txHash": h.hex()}


def balance_eth(address: str) -> float:
    web3 = w3()
    return float(web3.from_wei(web3.eth.get_balance(Web3.to_checksum_address(address)), "ether"))


def register_input(model_id, version, original_sha3, encrypted_sha3, merkle_root, metadata_sha3,
                   signature: bytes, pubkey_der: bytes, license_terms):
    """ABI tuple for ModelRegistry.RegisterInput (field order matters)."""
    b32 = lambda hx: bytes.fromhex(hx[2:] if hx.startswith("0x") else hx)
    return (model_id, version, b32(original_sha3), b32(encrypted_sha3), b32(merkle_root),
            b32(metadata_sha3), signature, pubkey_der, license_terms)


def register_model(private_key_hex: str, payload: tuple) -> dict:
    """Sign + send registerModel from the developer's own wallet (msg.sender = owner)."""
    acct = Account.from_key(private_key_hex)
    return _send(acct, contract().functions.registerModel(payload))


def try_register_real(private_key_hex: str, payload: tuple) -> dict:
    """
    Attempt a REAL registration transaction with a forced gas limit so that, if the contract
    rejects it, the failed transaction is still mined (status 0) and has a real hash.
    Returns {"accepted": bool, "reason": str, "txHash": str|None}.
    """
    acct = Account.from_key(private_key_hex)
    try:
        r = _send(acct, contract().functions.registerModel(payload), gas=900_000)
        return {"accepted": True, "reason": "transaction succeeded", "txHash": r["txHash"], "blockNumber": r["blockNumber"]}
    except ChainRevert as e:
        return {"accepted": False, "reason": e.reason, "txHash": e.tx_hash}


def preflight(fn, from_address: str) -> dict:
    """eth_call: executes the contract logic against current chain state without mining."""
    try:
        fn.call({"from": Web3.to_checksum_address(from_address)})
        return {"accepted": True, "reason": "call would succeed"}
    except Exception as e:
        return {"accepted": False, "reason": _reason(e)}


def preflight_register(from_address: str, payload: tuple) -> dict:
    return preflight(contract().functions.registerModel(payload), from_address)


def preflight_update_license(from_address: str, model_id: str, terms: str) -> dict:
    return preflight(contract().functions.updateLicense(model_id, terms), from_address)


def preflight_revoke(from_address: str, model_id: str) -> dict:
    return preflight(contract().functions.revokeModel(model_id), from_address)


# ------------------------------------------------------------------ reads (authoritative)
_FIELDS = ["modelId", "version", "creator", "originalHash", "encryptedHash", "merkleRoot", "metadataHash",
           "signature", "creatorPubKey", "licenseTerms", "registeredAt", "registeredBlock", "revoked", "exists"]


def get_record(model_id: str) -> Optional[dict]:
    """Reads the record straight from the chain. Returns None if not registered."""
    c = contract()
    if not c.functions.isRegistered(model_id).call():
        return None
    raw = c.functions.getRecord(model_id).call()
    r = dict(zip(_FIELDS, raw))
    for k in ("originalHash", "encryptedHash", "merkleRoot", "metadataHash"):
        r[k] = "0x" + bytes(r[k]).hex()
    r["signature"] = bytes(r["signature"]).hex()
    r["creatorPubKey"] = bytes(r["creatorPubKey"]).hex()
    r["registeredAt"], r["registeredBlock"] = int(r["registeredAt"]), int(r["registeredBlock"])
    return r


def list_registered() -> list:
    c = contract()
    return [c.functions.modelIdAt(i).call() for i in range(c.functions.modelCount().call())]


def confirm_registration(tx_hash: str, model_id: str) -> dict:
    """
    Verify a registration transaction made OUTSIDE the backend (e.g. from MetaMask): the tx must be
    mined successfully, sent to our contract, and emit ModelRegistered for this model id.
    """
    web3, c = w3(), contract()
    try:
        receipt = web3.eth.get_transaction_receipt(tx_hash)
    except Exception:
        raise ChainError("transaction not found / not mined yet")
    if receipt.status != 1:
        raise ChainError("transaction failed on-chain")
    if receipt["to"] is None or receipt["to"].lower() != c.address.lower():
        raise ChainError("transaction was not sent to the ModelRegistry contract")
    events = c.events.ModelRegistered().process_receipt(receipt)
    ev = next((e for e in events if e["args"]["modelId"] == model_id), None)
    if not ev:
        raise ChainError("transaction did not register this model id")
    block = web3.eth.get_block(receipt.blockNumber)
    return {"txHash": tx_hash, "blockNumber": receipt.blockNumber, "blockTimestamp": block["timestamp"],
            "gasUsed": receipt.gasUsed, "from": receipt["from"], "creator": ev["args"]["creator"]}
