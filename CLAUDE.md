# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AutoOps Agent - An intelligent operations CLI tool based on LangChain for automated cloud server and Kubernetes cluster management.

**Core Goals:**
- Lightweight, scalable CLI automation for ops tasks
- Autonomous task execution with multi-turn dialog control
- Three-layer memory system (short/medium/long-term)
- Plugin-based tool architecture
- Comprehensive audit logging

## Tech Stack (Planned)

- **Language:** Python
- **Core Framework:** LangChain
- **CLI Framework:** Click
- **K8s Integration:** Kubernetes Python Client
- **Security Tools:** OpenVAS, Nmap, kube-bench
- **System Monitoring:** psutil
- **Config:** YAML-based configuration with environment variable support
- **Audit Storage:** SQLite

## Architecture (Three Layers)

1. **CLI Interface** - Command parsing via Click
2. **Agent Core Layer** - Dialog state machine, task scheduler, context manager
3. **Tool Integration Layer** - Server tools (psutil), Security tools (OpenVAS/Nmap), K8s tools (kube-bench)
4. **Memory System** - Short-term (10 turns), Medium-term (compressed), Long-term (vector DB)

## CLI Command Structure

```
ops-agent [module] [operation] [parameters]

# Examples:
ops-agent server scan --host 192.168.1.1 --threshold 80
ops-agent k8s inspect --namespace default
ops-agent config save --profile production
```

## Core Modules (Planned)

| Module | Functionality |
|--------|---------------|
| server scan | Cloud server resource inspection |
| server inspect | Server vulnerability scanning |
| k8s inspect | K8s cluster resource inspection |
| k8s scan | K8s security compliance (CIS benchmark) |
| config | Multi-environment configuration management |
| auto-fix | Automated remediation (requires confirmation) |

## Configuration

- YAML-based config with profile support (development/production)
- Environment variables for sensitive data (passwords, API keys)
- Default thresholds: CPU 80%, Memory 85%, Disk 90%

## Security Model

- RBAC + ABAC hybrid permission model
- Secondary confirmation for high-risk operations
- Full audit logging to SQLite with log rotation
- Parameter whitelisting and sandbox execution

## Current State

**Repository Status:** Empty - requirements document only (README.md). No implementation code exists yet.

All development work is ahead. Start with Phase 1: Foundation framework (Python + LangChain setup, CLI basic interaction, simple command parsing, basic Memory system).
