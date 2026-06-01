"""
content_writer.py — Generates LinkedIn posts using Gemini 2.0 Flash.

Produces:
  - Hook line (scroll-stopper)
  - Post body (storytelling or insight-driven)
  - CTA (call to action)
  - Hashtags (5–8, relevant)
  - Image search keyword (for Unsplash)
  - Post type: text | image | carousel_script
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Literal, Optional

import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import config
from src.topic_engine import Topic

logger = logging.getLogger(__name__)

PostType = Literal["text", "image", "carousel_script"]


@dataclass
class GeneratedPost:
    topic: str
    hook: str
    body: str
    cta: str
    hashtags: list[str]
    image_query: str          # keyword for Unsplash search
    post_type: PostType
    full_text: str            # assembled final post text
    word_count: int


class ContentWriter:
    def __init__(self):
        genai.configure(api_key=config.gemini_api_key)
        self.model = genai.GenerativeModel(config.gemini_model)
        self._system_context = self._build_system_context()

    # ── Public interface ──────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=30, max=90))
    async def generate_post(self, topic: Topic) -> GeneratedPost:
        """Generate a complete LinkedIn post for a given topic."""
        prompt = self._build_prompt(topic)

        logger.info(f"ContentWriter: generating post for topic: {topic.title[:60]}")

        response = await self.model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.85,        # Creative but not unhinged
                top_p=0.92,
                max_output_tokens=4096,
            )
        )

        raw_text = response.text.strip()
        return self._parse_response(raw_text, topic)

    async def generate_multiple_posts(self, topic: "Topic", count: int = 2) -> list["GeneratedPost"]:
        """Generate multiple post variations sequentially to avoid rate limits."""
        posts = []
        for i in range(count):
            if i > 0:
                await asyncio.sleep(35)
            try:
                post = await self.generate_post(topic)
                posts.append(post)
            except Exception as e:
                logger.warning(f"Version {i + 1} generation failed: {e}")
        if not posts:
            raise ValueError("All post generation attempts failed")
        return posts

    async def generate_personal_story(self, topic: "Topic") -> "GeneratedPost":
        """Generate a personal story post — real experience, lesson learned."""
        prompt = f"""{self._system_context}

Topic for inspiration: {topic.title}

Write a LinkedIn post as a PERSONAL STORY. Jatin is sharing something real from his work life.

Rules:
- Start with a time anchor: "This week,", "Last month,", "3 years ago,"
- Share ONE specific moment/mistake/observation (not a list)
- Be vulnerable — share what went wrong or what surprised you
- What happened → what you learned → what changed
- End with a genuine question or bold 1-liner
- 120-200 words, conversational, no jargon

Return ONLY valid JSON:
{{
  "hook": "opening time-anchored sentence (15 words max)",
  "body": "the story in 3-4 short paragraphs",
  "cta": "closing question or statement",
  "hashtags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "image_query": "2-4 word Unsplash search query",
  "post_type": "image"
}}"""
        response = await self.model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.9, max_output_tokens=4096),
        )
        return self._parse_response(response.text.strip(), topic)

    async def generate_poll(self, topic: "Topic") -> dict:
        """Generate a LinkedIn poll with question + 4 options."""
        prompt = f"""{self._system_context}

Topic: {topic.title}

Create a LinkedIn poll that will drive maximum engagement.

Rules:
- Question: provocative, makes people think, under 120 characters
- 4 options: short (under 30 chars each), cover different viewpoints
- Intro text: 2-3 conversational sentences setting up the question
- Make it about opinions/choices, not facts with a right answer

Return ONLY valid JSON:
{{
  "intro_text": "2-3 sentence intro for the poll",
  "question": "The poll question?",
  "options": ["Option A", "Option B", "Option C", "Option D"],
  "hashtags": ["tag1", "tag2", "tag3", "tag4"]
}}"""
        response = await self.model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.85, max_output_tokens=500),
        )
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.text.strip(), flags=re.MULTILINE)
        return json.loads(raw)

    async def generate_carousel_slides(self, topic: "Topic") -> list[dict]:
        """Generate 5-6 slides for a LinkedIn carousel/PDF post."""
        prompt = f"""{self._system_context}

Topic: {topic.title}

Create a LinkedIn carousel (6 slides). Each slide is one screen — keep it tight.

Return ONLY valid JSON array:
[
  {{"slide": 1, "type": "hook", "title": "Bold 6-8 word headline", "content": "one line teaser"}},
  {{"slide": 2, "type": "content", "title": "Point title", "content": "2-3 short bullet points separated by newlines"}},
  {{"slide": 3, "type": "content", "title": "Point title", "content": "2-3 short bullet points"}},
  {{"slide": 4, "type": "content", "title": "Point title", "content": "2-3 short bullet points"}},
  {{"slide": 5, "type": "content", "title": "Point title", "content": "2-3 short bullet points"}},
  {{"slide": 6, "type": "cta", "title": "Key takeaway", "content": "What to do next + follow Jatin for more"}}
]"""
        response = await self.model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.8, max_output_tokens=1500),
        )
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.text.strip(), flags=re.MULTILINE)
        return json.loads(raw)

    async def generate_weekly_topics(self, count: int = 5) -> list[str]:
        """Generate topic ideas for the week's content calendar."""
        prompt = f"""Generate {count} LinkedIn post topic ideas for {config.your_name}, {config.your_role} at {config.your_company}.
Niche: {", ".join(config.your_niche)}

Requirements:
- Mix of types: industry insight, personal lesson, controversial take, how-to, trending
- Specific and timely — not generic
- Each topic max 15 words
- Think about what {config.your_name}'s audience (marketers, brand folks, startup people) would actually want to read

Return ONLY a valid JSON array of strings:
["topic 1", "topic 2", "topic 3", "topic 4", "topic 5"]"""
        response = await self.model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.9, max_output_tokens=500),
        )
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.text.strip(), flags=re.MULTILINE)
        return json.loads(raw)

    async def generate_post_from_article(self, url: str, article_text: str) -> "GeneratedPost":
        """Generate a LinkedIn post based on an article URL + its content."""
        from src.topic_engine import Topic
        prompt = f"""{self._system_context}

Article URL: {url}

Article content (excerpt):
{article_text[:2000]}

Read the article above and write a LinkedIn post sharing Jatin's take on it.
Rules:
- Don't summarise the article — share YOUR reaction, opinion, or a lesson it sparked
- Reference "I read something today" or "Came across this" to make it feel natural
- One specific insight or disagreement from the article, in Jatin's voice
- End with your own opinion or a question

Return ONLY valid JSON:
{{
  "hook": "Opening line — 10-15 words, scroll-stopper reaction to the article",
  "body": "3-4 short paragraphs sharing Jatin's take",
  "cta": "Closing question or bold statement",
  "hashtags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "image_query": "2-4 word Unsplash search query",
  "post_type": "image"
}}"""
        response = await self.model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.85, max_output_tokens=4096),
        )
        topic = Topic(title=f"Article: {url[:60]}", source="url", relevance_score=10.0)
        return self._parse_response(response.text.strip(), topic)

    async def generate_first_comment(self, post_text: str) -> str:
        """Generate a short first comment to boost LinkedIn algorithm reach."""
        prompt = f"""This LinkedIn post was just published:

{post_text[:500]}

Write a SHORT first comment (1-2 sentences max) to post right after it.
Rules:
- Add one extra insight or a personal observation
- End with a genuine question to invite responses
- Sound like Jatin texting a colleague, not a brand manager
- Under 200 characters total

Return ONLY the comment text. No quotes. No explanation."""

        response = await self.model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.7, max_output_tokens=100),
        )
        return response.text.strip()

    # ── Prompt engineering ────────────────────────────────────────────────────

    def _build_system_context(self) -> str:
        return f"""You are writing as {config.your_name}, a {config.your_role} at {config.your_company}.
Write in first person — as if Jatin himself is typing this post from his phone.

Writing rules (non-negotiable):
- Sound like a real human, not an AI or a copywriter
- Use "I", "we", "my team", "a client told me once" — personal anecdotes make it real
- Short sentences. Very short. One idea per line.
- No buzzwords: no "leverage", "synergy", "game-changer", "diving deep", "in today's fast-paced world"
- No listicles with emojis as bullets
- Vulnerability is powerful — share a mistake, a lesson learned, a moment of doubt
- Start mid-thought — like you're continuing a conversation, not giving a TED talk
- The best posts feel like a text message from a smart friend, not a press release
- End with a real question you actually want answered, or a provocative one-liner

BANNED punctuation and patterns (these are AI giveaways — never use):
- Em-dashes (—) — use a comma or full stop instead
- Colons to introduce points e.g. "Here is why: ..." — just say it directly
- "Here's the thing" / "Let me explain" / "The truth is" / "Here's what I learned"
- Numbered lists (1. 2. 3.)
- "In today's world" / "In the current landscape" / "It's important to note"
- Starting sentences with "Additionally", "Furthermore", "Moreover", "However,"
- "Navigating" / "Delve" / "Unlock" / "Harness" / "Pivotal" / "Transformative"

Topics {config.your_name} talks about: {", ".join(config.your_niche)}
"""

    def _build_prompt(self, topic: Topic) -> str:
        topic_context = f"Topic: {topic.title}"
        if topic.summary:
            topic_context += f"\nContext: {topic.summary[:300]}"

        return f"""{self._system_context}

---

{topic_context}

Write a high-performing LinkedIn post on this topic. Return ONLY valid JSON, no markdown, no explanation.

JSON schema (follow exactly):
{{
  "hook": "First line — 10-15 words max. Must be a scroll-stopper. A bold claim, a surprising stat, or a provocative question.",
  "body": "3-5 short paragraphs. Each paragraph max 3 sentences. Use line breaks. Share a specific insight, story, or observation. Be specific — avoid generic advice.",
  "cta": "One line. A genuine question that invites discussion or a bold closing statement. No 'let me know your thoughts'.",
  "hashtags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "image_query": "2-4 word Unsplash search query that visually represents this post. Be specific (e.g. 'brand packaging design' not just 'marketing')",
  "post_type": "image",
  "word_count_estimate": 150
}}

Rules:
- hashtags: 5-8 tags, no # symbol, lowercase, relevant to topic and {config.your_niche[0]}
- post_type: always "image" unless it's a list/tips post (then "carousel_script")
- Total post length: 150-280 words
- DO NOT include the hook in the body — they are separate fields
- Return ONLY the JSON object. No preamble, no explanation, no markdown backticks.
"""

    # ── Response parsing ──────────────────────────────────────────────────────

    def _parse_response(self, raw: str, topic: Topic) -> GeneratedPost:
        # Strip markdown code fences if Gemini wraps the JSON anyway
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)

        try:
            data = json.loads(clean)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini JSON response: {e}\nRaw: {raw[:500]}")
            raise ValueError(f"Gemini returned invalid JSON: {e}") from e

        # Validate required fields
        required = ["hook", "body", "cta", "hashtags", "image_query", "post_type"]
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"Gemini response missing fields: {missing}")

        hook = data["hook"].strip()
        body = data["body"].strip()
        cta = data["cta"].strip()
        hashtags = [f"#{h.lstrip('#').lower()}" for h in data["hashtags"][:8]]
        image_query = data["image_query"].strip()
        post_type: PostType = data.get("post_type", "image")

        # Assemble final post text
        hashtag_line = " ".join(hashtags)
        full_text = f"{hook}\n\n{body}\n\n{cta}\n\n{hashtag_line}"

        return GeneratedPost(
            topic=topic.title,
            hook=hook,
            body=body,
            cta=cta,
            hashtags=hashtags,
            image_query=image_query,
            post_type=post_type,
            full_text=full_text,
            word_count=len(full_text.split()),
        )
