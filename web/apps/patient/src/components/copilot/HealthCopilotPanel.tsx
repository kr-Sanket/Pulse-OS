// Patient Health Copilot panel for understanding medical records (P1.5).
//
// Allows authenticated patients to ask questions about their own medical records
// and receive plain-language, empathetic explanations grounded in verifiable evidence.

import { useState, type FormEvent, type KeyboardEvent } from "react";
import { AlertCircle, Bot, CheckCircle2, Info, Loader2, RotateCcw, Sparkles } from "lucide-react";

import {
  type AIAnswerResponse,
  type PulseOSClient,
  AIClientError,
  generatePatientSelfAnswer,
  getAIErrorMessage,
} from "@pulseos/api-client";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
  Textarea,
  cn,
} from "@pulseos/ui";

import { api } from "@/api";
import { CitationBadge } from "./CitationBadge";

export interface HealthCopilotPanelProps {
  onSelectCitation?: (recordId: string) => void;
  className?: string;
  client?: PulseOSClient;
}

export const MAX_QUESTION_LENGTH = 500;

/** The backend's fixed answer when none of your records matched — returned without calling
 * the model (`DEFAULT_EMPTY_EVIDENCE_ANSWER` in backend/app/modules/ai/query.py). */
export const NO_EVIDENCE_ANSWER =
  "The available medical records do not contain information regarding the requested topic.";

/**
 * Which of three answers this is. Only citations whose `[N]` marker appears in the text are
 * returned, so "no citations" is either the fixed no-evidence sentence or a model answer that
 * cited nothing — and the second must not be labelled "no matching records".
 */
export type AnswerKind = "cited" | "no-evidence" | "uncited";

export function answerKind(response: Pick<AIAnswerResponse, "answer" | "citations">): AnswerKind {
  if (response.citations.length > 0) {
    return "cited";
  }
  return response.answer.trim() === NO_EVIDENCE_ANSWER ? "no-evidence" : "uncited";
}

export const UNCITED_ANSWER_TITLE = "Answer without citations";
export const UNCITED_ANSWER_NOTE =
  "This answer could not be linked to any of your records. Check your records, or ask your doctor, before relying on it.";

export const SUGGESTED_QUESTIONS: readonly string[] = [
  "Summarize my active conditions",
  "Explain my latest lab reports",
  "What medications am I prescribed?",
  "When was my last vaccination?",
];

export function HealthCopilotPanel({
  onSelectCitation,
  className,
  client = api,
}: HealthCopilotPanelProps) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<AIAnswerResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const trimmedQuery = query.trim();
  const isQueryValid = trimmedQuery.length > 0 && trimmedQuery.length <= MAX_QUESTION_LENGTH;

  async function handleSubmit(e?: FormEvent) {
    if (e) {
      e.preventDefault();
    }
    if (!isQueryValid || loading) {
      return;
    }

    setLoading(true);
    setErrorMessage(null);

    try {
      const result = await generatePatientSelfAnswer(client, {
        query: trimmedQuery,
      });
      setResponse(result);
    } catch (err) {
      if (err instanceof AIClientError) {
        setErrorMessage(err.message);
      } else if (err instanceof Error) {
        setErrorMessage(err.message || "Could not generate clinical answer.");
      } else {
        setErrorMessage(getAIErrorMessage(500));
      }
      setResponse(null);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit();
    }
  }

  function handleClear() {
    setQuery("");
    setResponse(null);
    setErrorMessage(null);
  }

  function handleSuggestionClick(suggestion: string) {
    if (loading) {
      return;
    }
    setQuery(suggestion);
  }

  const kind = response === null ? null : answerKind(response);
  const isEvidenceEmpty = kind === "no-evidence";

  return (
    <Card className={cn("border-border shadow-sm", className)} data-testid="health-copilot-panel">
      <CardHeader className="space-y-1.5 pb-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="bg-primary/10 text-primary flex size-8 items-center justify-center rounded-lg">
              <Sparkles className="size-4" aria-hidden />
            </span>
            <CardTitle className="text-foreground text-lg font-semibold tracking-tight">
              PulseOS Health Copilot
            </CardTitle>
          </div>
          {response && (
            <Badge variant="outline" className="font-mono text-[11px] text-muted-foreground">
              {response.provider} / {response.model}
            </Badge>
          )}
        </div>
        <CardDescription className="text-muted-foreground text-xs leading-relaxed">
          Ask questions to help understand information in your medical records. The Health Copilot
          provides plain-language explanations cited from your records and is for educational
          support only.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Suggested Questions */}
        <div className="space-y-2">
          <span className="text-muted-foreground block text-xs font-medium">
            Suggested questions:
          </span>
          <div className="flex flex-wrap gap-1.5" data-testid="suggested-questions">
            {SUGGESTED_QUESTIONS.map((suggestion) => (
              <Button
                key={suggestion}
                type="button"
                variant="outline"
                size="sm"
                disabled={loading}
                onClick={() => handleSuggestionClick(suggestion)}
                className="h-7 text-xs font-normal text-muted-foreground hover:text-foreground"
                data-testid="suggested-question-chip"
              >
                {suggestion}
              </Button>
            ))}
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1.5">
            <Textarea
              id="health-copilot-query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading}
              placeholder="Ask a question about your records, e.g. What medications am I prescribed? Summarize my latest lab results."
              className="min-h-[80px] resize-y text-sm leading-relaxed"
              maxLength={MAX_QUESTION_LENGTH}
              aria-label="Ask Health Copilot a question"
              data-testid="health-copilot-textarea"
            />
            <div className="flex items-center justify-between text-[11px] text-muted-foreground px-0.5">
              <span>Press Enter to ask, Shift+Enter for new line</span>
              <span
                className={cn(
                  query.length > MAX_QUESTION_LENGTH ? "text-destructive font-medium" : "",
                )}
                data-testid="char-counter"
              >
                {`${query.length} / ${MAX_QUESTION_LENGTH}`}
              </span>
            </div>
          </div>

          <div className="flex items-center justify-between gap-2 pt-1">
            <Button
              type="submit"
              size="sm"
              disabled={!isQueryValid || loading}
              className="gap-2"
              data-testid="copilot-submit-button"
            >
              {loading ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" aria-hidden />
                  Analyzing records...
                </>
              ) : (
                <>
                  <Bot className="size-3.5" aria-hidden />
                  Ask Copilot
                </>
              )}
            </Button>

            {(response || errorMessage || query.length > 0) && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleClear}
                disabled={loading}
                className="text-xs text-muted-foreground hover:text-foreground"
                data-testid="copilot-clear-button"
              >
                Clear
              </Button>
            )}
          </div>
        </form>

        {/* Loading State */}
        {loading && (
          <div
            className="space-y-3 rounded-lg border border-border/60 bg-muted/30 p-4"
            data-testid="copilot-loading-state"
          >
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />
              <span>Analyzing your medical records...</span>
            </div>
            <div className="space-y-2">
              <Skeleton className="h-4 w-11/12" />
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          </div>
        )}

        {/* Error State */}
        {errorMessage && (
          <div
            className="flex items-start gap-3 rounded-lg border border-destructive/20 bg-destructive/10 p-3.5 text-xs text-destructive"
            role="alert"
            data-testid="copilot-error-state"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <div className="space-y-1 flex-1">
              <p className="font-medium text-[13px]">Health Copilot could not complete</p>
              <p className="leading-relaxed" data-testid="copilot-error-message">
                {errorMessage}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleSubmit()}
              className="h-7 text-xs gap-1.5 shrink-0 bg-background"
              data-testid="copilot-retry-button"
            >
              <RotateCcw className="size-3" aria-hidden />
              Retry
            </Button>
          </div>
        )}

        {/* Answer State */}
        {response && !loading && (
          <div
            className={cn(
              "space-y-4 rounded-lg border p-4.5 transition-colors",
              isEvidenceEmpty
                ? "border-blue-200/60 bg-blue-50/40 dark:border-blue-900/40 dark:bg-blue-950/20"
                : kind === "uncited"
                  ? "border-amber-200/70 bg-amber-50/40 dark:border-amber-900/40 dark:bg-amber-950/20"
                  : "border-border/80 bg-card",
            )}
            data-testid="copilot-answer-container"
            data-answer-kind={kind ?? undefined}
          >
            <div className="flex items-center gap-2">
              {isEvidenceEmpty ? (
                <>
                  <Info className="size-4 text-blue-600 dark:text-blue-400" aria-hidden />
                  <span className="text-xs font-semibold text-blue-900 dark:text-blue-300">
                    No matching medical records found
                  </span>
                </>
              ) : kind === "uncited" ? (
                <>
                  <AlertCircle className="size-4 text-amber-600 dark:text-amber-400" aria-hidden />
                  <span className="text-xs font-semibold text-amber-900 dark:text-amber-300">
                    {UNCITED_ANSWER_TITLE}
                  </span>
                </>
              ) : (
                <>
                  <CheckCircle2
                    className="size-4 text-emerald-600 dark:text-emerald-400"
                    aria-hidden
                  />
                  <span className="text-xs font-semibold text-foreground tracking-tight">
                    Health Copilot Explanation
                  </span>
                </>
              )}
            </div>

            <p
              className="text-foreground text-[14px] leading-relaxed whitespace-pre-line"
              data-testid="copilot-answer-text"
            >
              {response.answer}
            </p>

            {kind === "uncited" && (
              <p
                className="text-amber-900 dark:text-amber-300 text-xs leading-relaxed"
                data-testid="copilot-uncited-note"
              >
                {UNCITED_ANSWER_NOTE}
              </p>
            )}

            {response.citations.length > 0 && (
              <div
                className="space-y-2 pt-1 border-t border-border/60"
                data-testid="copilot-citations-section"
              >
                <span className="text-muted-foreground block text-xs font-medium">
                  Cited Records ({response.citations.length}):
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  {response.citations.map((citation) => (
                    <CitationBadge
                      key={`${citation.citationIndex}-${citation.recordId}`}
                      citationIndex={citation.citationIndex}
                      recordId={citation.recordId}
                      categoryCode={citation.categoryCode}
                      onClick={onSelectCitation}
                    />
                  ))}
                </div>
              </div>
            )}

            {response.disclaimer && (
              <div
                className="pt-2 border-t border-border/40 text-[11px] text-muted-foreground leading-normal italic"
                data-testid="copilot-disclaimer"
              >
                {response.disclaimer}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
