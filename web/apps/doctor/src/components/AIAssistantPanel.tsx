// Clinical AI Assistant panel for synthesizing answers from patient records (A5.1).
//
// Allows authorized clinicians to query consented patient records and receive
// grounded answers citing primary clinical records with provenance badges.

import { useState, type FormEvent, type KeyboardEvent } from "react";
import { AlertCircle, Bot, CheckCircle2, Info, Loader2, RotateCcw, Sparkles } from "lucide-react";

import {
  type AIAnswerResponse,
  type PulseOSClient,
  AIClientError,
  generatePatientAnswer,
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
import { CitationBadge } from "@/components/CitationBadge";

export interface AIAssistantPanelProps {
  patientId: string;
  patientHealthId?: string;
  onSelectCitation?: (recordId: string) => void;
  className?: string;
  client?: PulseOSClient;
}

export const MAX_QUESTION_LENGTH = 500;

export function AIAssistantPanel({
  patientId,
  patientHealthId,
  onSelectCitation,
  className,
  client = api,
}: AIAssistantPanelProps) {
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
      const result = await generatePatientAnswer(client, {
        patientId,
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

  const isEvidenceEmpty = response !== null && response.citations.length === 0;

  return (
    <Card className={cn("border-border shadow-sm", className)} data-testid="ai-assistant-panel">
      <CardHeader className="space-y-1.5 pb-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="bg-primary/10 text-primary flex size-8 items-center justify-center rounded-lg">
              <Sparkles className="size-4" aria-hidden />
            </span>
            <CardTitle className="text-foreground text-lg font-semibold tracking-tight">
              Clinical AI Assistant
            </CardTitle>
          </div>
          {response && (
            <Badge variant="outline" className="font-mono text-[11px] text-muted-foreground">
              {response.provider} / {response.model}
            </Badge>
          )}
        </div>
        <CardDescription className="text-muted-foreground text-xs leading-relaxed">
          Ask a clinical question about{" "}
          {patientHealthId ? <span className="font-mono">{patientHealthId}</span> : "this patient"}
          's consented records. Responses cite underlying medical records and do not replace
          clinical judgment.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1.5">
            <Textarea
              id="ai-clinical-query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading}
              placeholder="e.g. What medications were prescribed for hypertension? Summarize recent blood glucose findings."
              className="min-h-[80px] resize-y text-sm leading-relaxed"
              maxLength={MAX_QUESTION_LENGTH}
              aria-label="Clinical question"
            />
            <div className="flex items-center justify-between text-[11px] text-muted-foreground px-0.5">
              <span>Press Enter to ask, Shift+Enter for new line</span>
              <span
                className={cn(
                  query.length > MAX_QUESTION_LENGTH ? "text-destructive font-medium" : "",
                )}
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
              data-testid="ai-submit-button"
            >
              {loading ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" aria-hidden />
                  Synthesizing answer...
                </>
              ) : (
                <>
                  <Bot className="size-3.5" aria-hidden />
                  Ask Assistant
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
              >
                Clear
              </Button>
            )}
          </div>
        </form>

        {loading && (
          <div
            className="space-y-3 rounded-lg border border-border/60 bg-muted/30 p-4"
            data-testid="ai-loading-state"
          >
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />
              <span>Synthesizing answer from consented clinical evidence...</span>
            </div>
            <div className="space-y-2">
              <Skeleton className="h-4 w-11/12" />
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          </div>
        )}

        {errorMessage && (
          <div
            className="flex items-start gap-3 rounded-lg border border-destructive/20 bg-destructive/10 p-3.5 text-xs text-destructive"
            role="alert"
            data-testid="ai-error-state"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <div className="space-y-1 flex-1">
              <p className="font-medium text-[13px]">AI generation could not complete</p>
              <p className="leading-relaxed">{errorMessage}</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleSubmit()}
              className="h-7 text-xs gap-1.5 shrink-0 bg-background"
            >
              <RotateCcw className="size-3" aria-hidden />
              Retry
            </Button>
          </div>
        )}

        {response && !loading && (
          <div
            className={cn(
              "space-y-4 rounded-lg border p-4.5 transition-colors",
              isEvidenceEmpty
                ? "border-blue-200/60 bg-blue-50/40 dark:border-blue-900/40 dark:bg-blue-950/20"
                : "border-border/80 bg-card",
            )}
            data-testid="ai-answer-container"
          >
            <div className="flex items-center gap-2">
              {isEvidenceEmpty ? (
                <>
                  <Info className="size-4 text-blue-600 dark:text-blue-400" aria-hidden />
                  <span className="text-xs font-semibold text-blue-900 dark:text-blue-300">
                    No matching clinical evidence found
                  </span>
                </>
              ) : (
                <>
                  <CheckCircle2
                    className="size-4 text-emerald-600 dark:text-emerald-400"
                    aria-hidden
                  />
                  <span className="text-xs font-semibold text-foreground tracking-tight">
                    Synthesized Clinical Answer
                  </span>
                </>
              )}
            </div>

            <p
              className="text-foreground text-[14px] leading-relaxed whitespace-pre-line"
              data-testid="ai-answer-text"
            >
              {response.answer}
            </p>

            {response.citations.length > 0 && (
              <div
                className="space-y-2 pt-1 border-t border-border/60"
                data-testid="ai-citations-section"
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
              <div className="pt-2 border-t border-border/40 text-[11px] text-muted-foreground leading-normal italic">
                {response.disclaimer}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
