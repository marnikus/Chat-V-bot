"""Conversation sync, composed from seven cohesive modules.

Session owns shared data and orchestration; lifecycle owns admission/completion,
viewport owns settling/restoration, planning is pure, reading owns retries and
alignment, and persistence owns archive writes. backend.chat_sync only re-exports
compatibility names; phases never import that facade at module load.
"""
