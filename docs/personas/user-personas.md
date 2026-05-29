# User Personas & Journey Maps

## Persona 1: The Trauma-Aware Parent

**Name:** Maria, 38  
**Occupation:** Elementary school teacher  
**Tech comfort:** Moderate (uses smartphone daily, not a developer)

**Demographics:**
- Mother of two children (ages 9 and 13)
- Has a history of anxiety; specific triggers include scenes of drowning and animal harm
- Subscribes to Netflix, Disney+, and HBO Max

**Pain Points:**
- MPA ratings are too vague — "PG-13 for violence" tells her nothing specific
- Common Sense Media requires navigating multiple pages and reading long reviews
- She's been surprised by unexpected content in films she thought were safe
- Feels guilty fast-forwarding scenes her kids see

**Goals:**
- Know before pressing play whether a film has her specific triggers
- Get an answer in under 30 seconds
- Trust the source — wants AI that knows the film, not just guesses

**User Journey:**
```
Hears about a film
      │
      ▼
Opens ReelShield on phone
      │
      ▼
Types film title → sees results in <1 sec
      │
      ▼
Clicks film → waits ~10-15 sec for first load
      │
      ▼
Scans warning cards (sorted by severity)
      │
      ▼
Checks "Animal Abuse" card specifically → "✓ Confirmed absent"
      │
      ▼
Feels confident → watches with family
```

**Quote:** *"I don't need a full review. I just need to know: does the dog die? Is there anything that will give me a panic attack? Just tell me that."*

---

## Persona 2: The Photosensitive Gamer

**Name:** Jordan, 24  
**Occupation:** Software engineering student  
**Tech comfort:** High (developer, uses APIs, comfortable with technical tools)

**Demographics:**
- Diagnosed with photosensitive epilepsy at age 16
- Had a seizure during a film with unexpected strobe effects
- Active in gaming and film communities online

**Pain Points:**
- No reliable source for flashing light warnings in films
- MPA ratings never mention flashing lights
- Epilepsy Foundation warnings on some streaming platforms are inconsistent
- Has to rely on word-of-mouth from other epilepsy communities

**Goals:**
- Instantly know if a film has flashing lights before watching
- See specific notes (e.g. "during the final battle scene" vs "throughout")
- Share the tool with his epilepsy support group

**User Journey:**
```
Planning a movie night
      │
      ▼
Opens ReelShield
      │
      ▼
Searches film title
      │
      ▼
Immediately looks for epilepsy banner at top of page
      │
   Banner shown ──▶ Reads specific notes ──▶ Decides to skip
      │
   No banner ──▶ ✓ Confirmed absent ──▶ Watches with confidence
```

**Quote:** *"The red banner at the top is exactly what I need. I don't care about anything else — just tell me about the lights."*

---

## Persona 3: The Grief-Sensitive Viewer

**Name:** Priya, 31  
**Occupation:** Nurse  
**Tech comfort:** Moderate

**Demographics:**
- Recently experienced a miscarriage
- Currently in therapy; therapist recommends avoiding content around pregnancy loss
- Watches films to decompress after long shifts

**Pain Points:**
- Pregnancy loss scenes appear unexpectedly in many mainstream films
- No existing tool specifically flags this content category
- Doesn't want to read spoiler-heavy reviews just to check one thing

**Goals:**
- Filter films based on specific emotional triggers
- Spoiler-free answers only
- Trust that the AI actually knows the film, not just guessing

**User Journey:**
```
Looking for a film to watch after work
      │
      ▼
Opens ReelShield
      │
      ▼
Searches a film she's been curious about
      │
      ▼
Checks "Miscarriage / Pregnancy Loss" card
      │
   Severity > 0 ──▶ Chooses a different film
      │
   Severity = 0, ✓ Confirmed ──▶ Watches, relaxed
```

**Quote:** *"I'm not asking much. I just need to know if this specific thing is in the movie. Nobody else seems to track this."*

---

## Design Decisions Based on Personas

| Design Choice | Reason |
|---------------|--------|
| Epilepsy banner at very top | Jordan's journey: first thing epileptic users look for |
| Sort warnings by severity | Maria's journey: highest-risk items surface immediately |
| Spoiler-free by default | Priya's journey: trigger check shouldn't spoil the film |
| Confidence display (✓ Confirmed) | Maria + Priya: they need to trust the source |
| Specific notes field | Jordan: "during final battle" is more useful than just "yes" |
| Chat feature | All personas: follow-up questions without leaving the page |
| Dark theme | Jordan: photosensitivity means reduced eye strain matters |
| WCAG 2.1 AA | Jordan: screen reader users may also use accessibility tools |
