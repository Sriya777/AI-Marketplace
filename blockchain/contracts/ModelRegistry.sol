// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title ModelRegistry
/// @notice Authoritative on-chain record of AI-model integrity and ownership.
///
/// What is stored on-chain: hashes, the Merkle root, the signed-metadata hash, the
/// developer's ECDSA signature + public key, license text, timestamps and the owner wallet.
/// What is NEVER stored: the model file, the plaintext, or any encryption key.
///
/// Security properties enforced by the contract:
///  * Only wallets authorized by the marketplace admin may register models
///  * msg.sender becomes the immutable owner of a model record
///  * A model id can be registered exactly once (duplicate registration reverts)
///  * Hashes / Merkle root / signature can never be modified after registration
///  * Only the owner can change the license text or revoke the model
///
/// The developer signature is ECDSA over NIST P-256. The EVM has no native P-256
/// verifier, so the signature + public key are stored as a verification reference and
/// checked off-chain by anyone who reads the record (see backend/app/verification.py).
contract ModelRegistry {
    struct RegisterInput {
        string  modelId;
        string  version;
        bytes32 originalHash;   // SHA3-256 of the plaintext model artifact
        bytes32 encryptedHash;  // SHA3-256 of the AES-256-GCM encrypted artifact
        bytes32 merkleRoot;     // Merkle root over the encrypted artifact chunks
        bytes32 metadataHash;   // SHA3-256 of the canonical metadata that was signed
        bytes   signature;      // ECDSA(P-256, SHA3-256) signature over canonical metadata (DER)
        bytes   creatorPubKey;  // signer public key (DER SubjectPublicKeyInfo)
        string  licenseTerms;
    }

    struct ModelRecord {
        string  modelId;
        string  version;
        address creator;
        bytes32 originalHash;
        bytes32 encryptedHash;
        bytes32 merkleRoot;
        bytes32 metadataHash;
        bytes   signature;
        bytes   creatorPubKey;
        string  licenseTerms;
        uint64  registeredAt;
        uint64  registeredBlock;
        bool    revoked;
        bool    exists;
    }

    address public immutable admin;
    mapping(address => bool) public authorizedDevelopers;
    mapping(bytes32 => ModelRecord) private records;
    bytes32[] private modelKeys;

    event DeveloperAuthorized(address indexed developer);
    event DeveloperRevoked(address indexed developer);
    event ModelRegistered(bytes32 indexed key, string modelId, address indexed creator,
                          bytes32 originalHash, bytes32 merkleRoot);
    event LicenseUpdated(bytes32 indexed key, string newLicenseTerms);
    event ModelRevoked(bytes32 indexed key, address indexed by);

    constructor() {
        admin = msg.sender;
        authorizedDevelopers[msg.sender] = true;
        emit DeveloperAuthorized(msg.sender);
    }

    modifier onlyAdmin() {
        require(msg.sender == admin, "Only admin");
        _;
    }

    modifier onlyAuthorizedDeveloper() {
        require(authorizedDevelopers[msg.sender], "Not an authorized developer");
        _;
    }

    modifier onlyOwner(string calldata modelId) {
        ModelRecord storage r = records[keyOf(modelId)];
        require(r.exists, "Model not found");
        require(r.creator == msg.sender, "Not the model owner");
        _;
    }

    // ------------------------------------------------------------ administration
    function authorizeDeveloper(address developer) external onlyAdmin {
        require(developer != address(0), "Zero address");
        authorizedDevelopers[developer] = true;
        emit DeveloperAuthorized(developer);
    }

    function revokeDeveloper(address developer) external onlyAdmin {
        authorizedDevelopers[developer] = false;
        emit DeveloperRevoked(developer);
    }

    // ------------------------------------------------------------ registration
    function registerModel(RegisterInput calldata p) external onlyAuthorizedDeveloper returns (bytes32 key) {
        require(bytes(p.modelId).length > 0 && bytes(p.modelId).length <= 96, "Invalid model id");
        require(p.originalHash != bytes32(0) && p.encryptedHash != bytes32(0)
                && p.merkleRoot != bytes32(0) && p.metadataHash != bytes32(0), "Invalid hash");
        require(p.signature.length > 0 && p.creatorPubKey.length > 0, "Missing signature");

        key = keyOf(p.modelId);
        ModelRecord storage r = records[key];
        require(!r.exists, "Model already registered");

        r.modelId = p.modelId;
        r.version = p.version;
        r.creator = msg.sender;
        r.originalHash = p.originalHash;
        r.encryptedHash = p.encryptedHash;
        r.merkleRoot = p.merkleRoot;
        r.metadataHash = p.metadataHash;
        r.signature = p.signature;
        r.creatorPubKey = p.creatorPubKey;
        r.licenseTerms = p.licenseTerms;
        r.registeredAt = uint64(block.timestamp);
        r.registeredBlock = uint64(block.number);
        r.exists = true;
        modelKeys.push(key);

        emit ModelRegistered(key, p.modelId, msg.sender, p.originalHash, p.merkleRoot);
    }

    // ------------------------------------------------------------ owner-only operations
    function updateLicense(string calldata modelId, string calldata newTerms) external onlyOwner(modelId) {
        ModelRecord storage r = records[keyOf(modelId)];
        require(!r.revoked, "Model revoked");
        r.licenseTerms = newTerms;
        emit LicenseUpdated(keyOf(modelId), newTerms);
    }

    function revokeModel(string calldata modelId) external onlyOwner(modelId) {
        ModelRecord storage r = records[keyOf(modelId)];
        require(!r.revoked, "Model revoked");
        r.revoked = true;
        emit ModelRevoked(keyOf(modelId), msg.sender);
    }

    // ------------------------------------------------------------ reads
    function keyOf(string memory modelId) public pure returns (bytes32) {
        return keccak256(bytes(modelId));
    }

    function isRegistered(string calldata modelId) external view returns (bool) {
        return records[keyOf(modelId)].exists;
    }

    function getRecord(string calldata modelId) external view returns (ModelRecord memory) {
        ModelRecord storage r = records[keyOf(modelId)];
        require(r.exists, "Model not found");
        return r;
    }

    function modelCount() external view returns (uint256) {
        return modelKeys.length;
    }

    function modelIdAt(uint256 index) external view returns (string memory) {
        require(index < modelKeys.length, "Index out of range");
        return records[modelKeys[index]].modelId;
    }
}
