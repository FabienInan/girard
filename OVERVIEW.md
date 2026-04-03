# Girard — Your AI Sales Prospecting Agent

> **What it does:** Finds qualified leads for any business, in any industry, anywhere in the world.

---

## The Problem It Solves

You have a product or service. You need customers. But finding the right prospects takes hours of manual work:

- Searching Google for potential clients
- Visiting each website to understand their business
- Deciding if they're a good fit
- Collecting their information

**Girard automates all of this.**

---

## How It Works (In Plain English)

### Step 1: You Describe Your Ideal Customer

Just tell Girard what you're selling and who you want to reach. For example:

```
"I sell CRM software to construction companies in France with 10-50 employees.
I want to reach owners and general managers who are likely growing and need
better project tracking."
```

Girard will figure out:
- Your industry sector
- Key sub-sectors to target (electricians, plumbers, general contractors...)
- Company size range
- Geographic focus (France, Quebec, US...)
- Decision-maker titles (owner, GM, project manager...)
- Buying signals to look for (job postings, growth announcements...)
- Pain points your offer solves

### Step 2: Girard Searches Google

It creates smart search queries and finds candidate websites:
- "/about" pages (company info)
- "/team" pages (decision makers)
- "/contact" pages
- Job postings (growth signal)

### Step 3: It Visits and Qualifies Each Website

For each candidate, Girard:
1. Fetches the website content
2. Extracts the text (removing navigation, ads, etc.)
3. Uses AI to analyze if this company matches your ideal customer
4. Outputs: **qualified leads with company name, industry, and why they fit**

### Step 4: Results Saved Automatically

All qualified prospects are saved to a simple file (`prospects.jsonl`) with:
- Company name
- Industry
- Why they're a good fit
- Signals detected (hiring, growing, etc.)
- Website URL

---

## What Makes It Different

### Adapts to Any Business

Unlike hardcoded systems, Girard generates custom examples for each run. Selling to dentists in California? Electricians in Quebec? Software companies in Germany? The AI creates tailored qualification criteria automatically.

### Learns From Success

The system is designed to learn over time:
- Which messages get responses
- Which signals predict actual interest
- Which industries convert best

### Cost-Effective

Uses open-source AI models hosted on Ollama Cloud:
- Free tier available
- Pay only for what you use
- No vendor lock-in

---

## Current Status

| Module | Status | What It Does |
|--------|--------|--------------|
| **M1: Prospecting** | ✅ Ready | Find and qualify leads |
| **M2: Contact Enrichment** | 🔲 Coming | Find decision-maker emails |
| **M3: Personalization** | 🔲 Coming | Write tailored outreach emails |
| **M4: Follow-up** | 🔲 Coming | Schedule and track follow-ups |

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up API Keys

Create a `.env` file:

```
ZYTE_API_KEY=your_zyte_key
OLLAMA_API_KEY=your_ollama_key
OLLAMA_MODEL=ministral-3:8b
```

### Available Models

| Model | Size | Best For | Notes |
|-------|------|----------|-------|
| `ministral-3:8b` | 8B | Fast classification, validation | **Recommended default** |
| `gemma3:12b` | 12B | Better ICP generation | Higher quality, slower |
| `gpt-oss:20b` | 20B | Alternative | Good for complex tasks |

**Avoid** "thinking" models (`qwen3.5`, `deepseek`) — they don't return clean JSON.

Get your keys:
- **Zyte:** https://zyte.com (for web scraping)
- **Ollama:** https://ollama.com/settings (for AI)

### 3. Run

```bash
python main.py
```

You'll be prompted to describe your ideal customer. Or use CLI args:

```bash
python main.py --phrase "I sell X to Y companies in Z region" --target 20
```

---

## Cost Estimates

Using Ollama Cloud's free tier:

| Prospects Targeted | API Calls | Estimated Cost |
|--------------------|-----------|-----------------|
| 20 | ~25 | ~$0.03 |
| 50 | ~60 | ~$0.08 |
| 100 | ~120 | ~$0.15 |

Costs scale linearly. Zyte API costs apply separately (~$0.002 per page).

---

## Architecture (For Technical Readers)

```
User Input (phrase describing ideal customer)
        │
        ▼
    ┌─────────────────────────────────────────┐
    │  ICP Generator (AI)                      │
    │  Creates Ideal Customer Profile          │
    │  + custom validation examples            │
    └─────────────────────────────────────────┘
        │
        ▼
    ┌─────────────────────────────────────────┐
    │  Google Search (Zyte API)                │
    │  Finds candidate websites                │
    │  Filters out job boards, directories     │
    └─────────────────────────────────────────┘
        │
        ▼
    ┌─────────────────────────────────────────┐
    │  Website Validator (AI)                  │
    │  Visits each site, extracts text         │
    │  Qualifies against ICP (3 in parallel)   │
    └─────────────────────────────────────────┘
        │
        ▼
    Qualified Prospects (JSONL file)
```

---

## What's Next

### Module 2: Contact Enrichment
Find the actual person to contact:
- Scrape company "team" pages
- Query Hunter.io / Apollo for emails
- Cross-reference with LinkedIn

### Module 3: Personalized Outreach
Generate tailored cold emails using:
- Company signals (hiring, growth, pain points)
- Industry-specific templates
- Past successful messages (RAG learning)

### Module 4: Follow-up Automation
- Schedule follow-ups (day 3, 7, 14)
- Detect intent from replies
- Sync with your CRM (HubSpot, Notion)

---

## Questions?

**Q: Which model should I use?**
A: Start with `ministral-3:8b` — it's fast and handles JSON well. Switch to `gemma3:12b` if you need more nuanced ICP generation.

**Q: Can I use other AI providers?**
A: Yes. The code uses LangChain, so you can swap Ollama for OpenAI, Anthropic, etc. Modify `modules/m1_prospect_finder.py` to use a different LLM.

**Q: What countries does it support?**
A: Any country. The AI detects geography from your description automatically (France, Canada, US, Germany, etc.).

**Q: How accurate is the qualification?**
A: Depends on your ICP description. The AI uses dynamic few-shot examples tailored to your specific offer, which improves accuracy over generic prompts.

**Q: Can I exclude certain domains?**
A: Yes. The ICP generator can suggest exclusions (competitors, directories, etc.) and you can add manual exclusions.

---

*Built with Python + LangChain + Ollama Cloud + Zyte API.*
*Open for extensions, contributions welcome.*