// Date and time formatting for every portal, in one place.
//
// Three functions because the API returns three different kinds of value, and they must
// not be formatted the same way:
//
//   • a calendar date ("2026-08-24") has no time zone — format it in UTC, or it slips a
//     day for readers west of Greenwich;
//   • an instant ("2026-08-24T10:00:00Z") is a moment — format it locally;
//   • an instant the reader thinks of as recency ("2 hours ago") reads better relative.
//
// Unparseable input is returned verbatim rather than as "Invalid Date": a wrong-looking
// value is more useful than a broken one, and it never throws in a render.

const CALENDAR_DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const INSTANT_DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

const INSTANT_TIME = new Intl.DateTimeFormat("en-IN", {
  hour: "numeric",
  minute: "2-digit",
});

const RELATIVE = new Intl.RelativeTimeFormat("en-IN", { numeric: "auto" });

function format(formatter: Intl.DateTimeFormat, iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : formatter.format(parsed);
}

/** "2026-08-24" → "24 Aug 2026", in UTC because a calendar date has no zone. */
export function formatCalendarDate(iso: string): string {
  return format(CALENDAR_DATE, iso);
}

/** An ISO timestamp as a local calendar date. */
export function formatInstantDate(iso: string): string {
  return format(INSTANT_DATE, iso);
}

/** An ISO timestamp as a local clock time — "10:42 am". */
export function formatInstantTime(iso: string): string {
  return format(INSTANT_TIME, iso);
}

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const MONTH = 30 * DAY;

/** An ISO timestamp as "2 hours ago" / "yesterday" / "in 6 days", relative to `now`.
 * `now` is injectable so the rule is testable without freezing the clock. */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const parsed = new Date(iso).getTime();
  if (Number.isNaN(parsed)) {
    return iso;
  }
  const seconds = Math.round((parsed - now) / 1000);
  const magnitude = Math.abs(seconds);
  if (magnitude < MINUTE) {
    return RELATIVE.format(seconds, "second");
  }
  if (magnitude < HOUR) {
    return RELATIVE.format(Math.round(seconds / MINUTE), "minute");
  }
  if (magnitude < DAY) {
    return RELATIVE.format(Math.round(seconds / HOUR), "hour");
  }
  if (magnitude < MONTH) {
    return RELATIVE.format(Math.round(seconds / DAY), "day");
  }
  return RELATIVE.format(Math.round(seconds / MONTH), "month");
}
