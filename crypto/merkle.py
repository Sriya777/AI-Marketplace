"""
merkle.py
Integrity layer: Merkle tree over fixed-size chunks of the (encrypted) model file.

Hardened vs. the textbook construction:
  * domain separation   leaf = SHA3(0x00 || chunk),  node = SHA3(0x01 || left || right)
    (prevents leaf/internal-node confusion = second-preimage attacks)
  * odd nodes are PROMOTED unchanged instead of duplicated
    (duplication makes [a,b,c] and [a,b,c,c] collide - CVE-2012-2459 style)
"""

import hashlib

CHUNK_SIZE = 16 * 1024  # bytes per leaf (default)

_LEAF = b"\x00"
_NODE = b"\x01"


def _h(data: bytes) -> bytes:
    return hashlib.sha3_256(data).digest()


def leaf_hash(chunk: bytes) -> bytes:
    return _h(_LEAF + chunk)


def _node_hash(left: bytes, right: bytes) -> bytes:
    return _h(_NODE + left + right)


def chunk_file(path: str, chunk_size: int = CHUNK_SIZE):
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk


def chunk_bytes(data: bytes, chunk_size: int = CHUNK_SIZE):
    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]


def leaves_from_chunks(chunks) -> list:
    return [leaf_hash(c) for c in chunks]


def build_tree_from_leaves(leaves: list) -> list:
    """Returns levels: level[0] = leaf hashes ... level[-1] = [root]."""
    if not leaves:
        return [[_h(_LEAF)]]
    tree = [list(leaves)]
    level = tree[0]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(_node_hash(level[i], level[i + 1]))
            else:
                nxt.append(level[i])          # promote odd node
        tree.append(nxt)
        level = nxt
    return tree


def build_merkle_tree(chunks) -> list:
    return build_tree_from_leaves(leaves_from_chunks(chunks))


def root_from_leaves(leaves: list) -> str:
    return build_tree_from_leaves(leaves)[-1][0].hex()


def merkle_root(chunks) -> str:
    return build_merkle_tree(chunks)[-1][0].hex()


def get_proof(tree: list, leaf_index: int) -> list:
    """Sibling path [(sibling_hex, sibling_is_left), ...] from leaf to root."""
    proof = []
    idx = leaf_index
    for level in tree[:-1]:
        sib = idx ^ 1
        if sib < len(level):
            proof.append((level[sib].hex(), sib < idx))
        idx //= 2
    return proof


def verify_proof(leaf_data: bytes, proof: list, root_hex: str) -> bool:
    """Recompute the root from raw chunk bytes + proof path."""
    cur = leaf_hash(leaf_data)
    for sibling_hex, is_left in proof:
        sib = bytes.fromhex(sibling_hex)
        cur = _node_hash(sib, cur) if is_left else _node_hash(cur, sib)
    return cur.hex() == root_hex
