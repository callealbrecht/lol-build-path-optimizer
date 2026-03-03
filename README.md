# LoL Optimal Build Path Optimizer

A matchup-aware build path recommender for League of Legends trained on Emerald+ ranked data using Riot’s official API.

**Live demo:**  
https://lol-build-path-optimizer.onrender.com/


## Overview

This project recommends the first three completed items for a champion based on:

- Patch  
- Role  
- Lane opponent  
- Enemy team composition  

The system extracts real build order from match timelines and applies matchup-aware winrate reranking with structured fallback logic when data is sparse.


## Data Pipeline

Data collected from Riot API:

1. Seed Emerald+ player PUUIDs  
2. Fetch match IDs  
3. Fetch match details  
4. Fetch match timelines  
5. Extract first three completed items per player  
6. Build modeling dataset
