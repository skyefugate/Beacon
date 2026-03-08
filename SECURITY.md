# Security Policy

## Supported Versions

Before version 1.0, only the latest development version (main branch) is supported with security updates.

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in Beacon, please report it responsibly:

**DO NOT** open a public GitHub issue for security vulnerabilities.

Instead, please email security details to: **beacon-security@fugate.dev**

### What to Include

Please include the following information in your report:

- Description of the vulnerability
- Steps to reproduce the issue
- Potential impact
- Any suggested fixes (if you have them)

### What to Expect

- **Acknowledgment**: We aim to acknowledge receipt of your vulnerability report within 48 hours
- **Updates**: We'll keep you informed about our progress addressing the issue
- **Timeline**: We will make a good-faith effort to address critical vulnerabilities promptly, ideally within 30 days
- **Credit**: If you'd like, we'll credit you in the security advisory (or keep you anonymous if you prefer)

## Security Best Practices

When deploying Beacon:

- Keep your Python dependencies up to date
- Use environment variables for sensitive configuration (never commit secrets)
- Run Beacon with minimal required privileges
- Use TLS/SSL for API endpoints in production
- Regularly review and rotate API keys
- Monitor logs for suspicious activity

## Disclosure Policy

- We'll work with you to understand and resolve the issue
- Once fixed, we'll publish a security advisory
- We'll credit researchers who report vulnerabilities responsibly

Thank you for helping keep Beacon and its users safe!
