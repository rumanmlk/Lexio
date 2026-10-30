-- Daily counters that keep a public demo inside the free tiers (see app/budget.py).
-- `day` is the calendar day in Pacific time, which is when Gemini's daily quota resets.
CREATE TABLE daily_usage (
    day     date   NOT NULL,
    counter text   NOT NULL,
    used    bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (day, counter)
);
