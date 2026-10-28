# Security

Do not post pairing keys, network passwords, private endpoint URLs, firmware backups or memory dumps in public issues. Diagnostics redact common credentials, but review exports before sharing them.

Use GitHub's **Report a vulnerability** entry for a private report when it is enabled. If it is unavailable, contact a repository maintainer to establish a private channel before sending details; do not disclose an exploit or secret in a public issue.

The management HTTP interface is for trusted local networks. A local authenticated WebSocket site is not automatically a TLS-protected public endpoint. Public remote access and TLS deployment need their own configuration and verification.

This is a hardware debugging tool. Users must control the target, maintain verified backups and avoid writes on unknown device identities. Safe failure and unknown-result isolation are part of the protocol, not reasons to replay a failed write.
