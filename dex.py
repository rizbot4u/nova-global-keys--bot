"""DKHYR on Base Mainnet."""
import os
from web3 import Web3

DKHYR_ADDRESS = "0x9991bE994829601F90328CCF9cee4D1A55ADae70"
DKHYR_DECIMALS = 18
BASE_RPC = os.environ.get("BASE_RPC", "https://mainnet.base.org")

_ABI = [
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "a", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "transfer", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "to", "type": "address"}, {"name": "amt", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
]

_w3 = None
_contract = None
try:
    _w3 = Web3(Web3.HTTPProvider(BASE_RPC))
    if _w3.is_connected():
        _contract = _w3.eth.contract(
            address=Web3.to_checksum_address(DKHYR_ADDRESS), abi=_ABI)
    else:
        _w3 = None
except Exception:
    pass


def connected() -> bool:
    return _w3 is not None


def balance(address: str) -> float:
    if not _contract:
        return 0.0
    try:
        raw = _contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
        return raw / (10 ** DKHYR_DECIMALS)
    except Exception:
        return 0.0


def transfer(to_addr: str, amount: float):
    pk = os.environ.get("TREASURY_PRIVATE_KEY", "")
    if not _w3 or not pk:
        return None
    try:
        acct = _w3.eth.account.from_key(pk)
        raw = int(amount * 10 ** DKHYR_DECIMALS)
        tx = _contract.functions.transfer(
            Web3.to_checksum_address(to_addr), raw
        ).build_transaction({
            "from": acct.address,
            "nonce": _w3.eth.get_transaction_count(acct.address),
            "gas": 100000,
            "gasPrice": _w3.eth.gas_price,
        })
        signed = acct.sign_transaction(tx)
        return _w3.eth.send_raw_transaction(signed.rawTransaction).hex()
    except Exception as e:
        print(f"dex.transfer error: {e}")
        return None
