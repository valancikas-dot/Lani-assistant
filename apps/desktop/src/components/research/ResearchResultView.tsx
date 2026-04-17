/**
 * ResearchResultView – renders the structured output of research plan steps.
 *
 * Sections rendered (only when data is present):
 *   1. ResearchBrief       (research_and_prepare_brief step)
 *   2. Search results list (web_search step)
 *   3. Summary card        (summarize_web_results step)
 *   4. Comparison table    (compare_research_results step)
 *
 * The component is intentionally self-contained so it can also be embedded
 * in a future dedicated ResearchPage if needed.
 */

import React, { useState } from "react";
import type {
  ResearchStepData,
  SearchResult,
  SourceSummary,
  ComparedItem,
  CompareResponse,
  SummarizeResponse,
  WebSearchResponse,
  ResearchBrief,
} from "../../lib/types";

interface Props {
  data: ResearchStepData;
}

export const ResearchResultView: React.FC<Props> = ({ data }) => {
  // Brief covers everything; only show sub-sections when brief is absent
  if (data.brief) {
    return <BriefBlock brief={data.brief} />;
  }

  return (
    <div className="research-result">
      {data.search && <SearchResultsBlock search={data.search} />}
      {data.summary && <SummaryBlock summary={data.summary} />}
      {data.comparison && <ComparisonBlock comparison={data.comparison} />}
    </div>
  );
};

// ─── Research Brief ───────────────────────────────────────────────────────────

const BriefBlock: React.FC<{ brief: ResearchBrief }> = ({ brief }) => {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="research-brief">
      <div className="research-brief__header">
        <span className="research-brief__icon">🔍</span>
        <span className="research-brief__title">Research Brief</span>
        <span className="research-brief__query">"{brief.query}"</span>
        <button
          className="research-brief__toggle"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "▲ Collapse" : "▼ Expand"}
        </button>
      </div>

      <p className="research-brief__summary">{brief.summary}</p>

      {brief.key_points.length > 0 && (
        <ul className="research-brief__key-points">
          {brief.key_points.map((pt, i) => (
            <li key={i} className="research-brief__key-point">
              {pt}
            </li>
          ))}
        </ul>
      )}

      {expanded && (
        <>
          {brief.top_sources.length > 0 && (
            <SourcesList sources={brief.top_sources} />
          )}
          {brief.comparison && (
            <ComparisonBlock comparison={brief.comparison} />
          )}
        </>
      )}
    </div>
  );
};

// ─── Search Results ───────────────────────────────────────────────────────────

const SearchResultsBlock: React.FC<{ search: WebSearchResponse }> = ({ search }) => {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? search.results : search.results.slice(0, 4);

  return (
    <div className="research-search">
      <div className="research-section-title">
        🌐 Search Results
        <span className="research-count">{search.total_results} found</span>
      </div>
      <div className="research-search__list">
        {visible.map((r, i) => (
          <SearchResultCard key={i} result={r} />
        ))}
      </div>
      {search.results.length > 4 && (
        <button
          className="research-show-more"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll ? "Show less" : `Show ${search.results.length - 4} more`}
        </button>
      )}
      {search.error && (
        <p className="research-error">⚠ {search.error}</p>
      )}
    </div>
  );
};

const SearchResultCard: React.FC<{ result: SearchResult }> = ({ result }) => (
  <a
    className="research-search__card"
    href={result.url}
    target="_blank"
    rel="noopener noreferrer"
  >
    <div className="research-search__card-domain">{result.source_domain}</div>
    <div className="research-search__card-title">{result.title}</div>
    <div className="research-search__card-snippet">{result.snippet}</div>
  </a>
);

// ─── Summary ──────────────────────────────────────────────────────────────────

const SummaryBlock: React.FC<{ summary: SummarizeResponse }> = ({ summary }) => (
  <div className="research-summary">
    <div className="research-section-title">
      📄 Summary
      <span className="research-count">
        {summary.sources_succeeded}/{summary.sources_attempted} sources
      </span>
    </div>

    <p className="research-summary__text">{summary.overall_summary}</p>

    {summary.key_points.length > 0 && (
      <ul className="research-summary__points">
        {summary.key_points.map((pt, i) => (
          <li key={i}>{pt}</li>
        ))}
      </ul>
    )}

    {summary.sources.length > 0 && (
      <div className="research-summary__sources">
        <div className="research-section-subtitle">Sources</div>
        {summary.sources.map((s, i) => (
          <SourceRow key={i} source={s} />
        ))}
      </div>
    )}

    {summary.error && <p className="research-error">⚠ {summary.error}</p>}
  </div>
);

const SourceRow: React.FC<{ source: SourceSummary }> = ({ source }) => (
  <div className={`research-source-row${source.fetched ? "" : " research-source-row--failed"}`}>
    {source.fetched ? (
      <a href={source.url} target="_blank" rel="noopener noreferrer" className="research-source-link">
        <span className="research-source-title">{source.title || source.url}</span>
        {source.snippet && (
          <span className="research-source-snippet">{source.snippet.slice(0, 120)}…</span>
        )}
      </a>
    ) : (
      <span className="research-source-failed">✗ {source.url} (failed to load)</span>
    )}
  </div>
);

// ─── Comparison Table ─────────────────────────────────────────────────────────

const ComparisonBlock: React.FC<{ comparison: CompareResponse }> = ({ comparison }) => {
  if (!comparison.compared_items.length) {
    return (
      <div className="research-comparison">
        <div className="research-section-title">⚖️ Comparison</div>
        <p className="research-empty">{comparison.error ?? "No items to compare."}</p>
      </div>
    );
  }

  return (
    <div className="research-comparison">
      <div className="research-section-title">
        ⚖️ Comparison — {comparison.topic}
      </div>

      <div className="research-comparison__table-wrap">
        <table className="research-comparison__table">
          <thead>
            <tr>
              <th>Source</th>
              {comparison.criteria.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {comparison.compared_items.map((item, i) => (
              <ComparisonRow key={i} item={item} criteria={comparison.criteria} />
            ))}
          </tbody>
        </table>
      </div>

      {comparison.conclusion && (
        <p className="research-comparison__conclusion">
          💡 {comparison.conclusion}
        </p>
      )}
    </div>
  );
};

const ComparisonRow: React.FC<{ item: ComparedItem; criteria: string[] }> = ({
  item,
  criteria,
}) => {
  const maxScore = Math.max(...criteria.map((c) => (item.scores[c] as number) ?? 0), 1);
  return (
    <tr>
      <td>
        <a href={item.url} target="_blank" rel="noopener noreferrer" className="research-comparison__item-name">
          {item.name}
        </a>
        {item.summary && (
          <div className="research-comparison__item-summary">
            {item.summary.slice(0, 100)}…
          </div>
        )}
      </td>
      {criteria.map((c) => {
        const raw = (item.scores[c] as number) ?? 0;
        const pct = Math.round((raw / maxScore) * 100);
        return (
          <td key={c} className="research-comparison__score-cell">
            <div className="research-score-bar">
              <div
                className="research-score-bar__fill"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="research-score-label">{raw}</span>
          </td>
        );
      })}
    </tr>
  );
};

// ─── Sources list (used in brief expanded view) ───────────────────────────────

const SourcesList: React.FC<{ sources: SearchResult[] }> = ({ sources }) => (
  <div className="research-sources-list">
    <div className="research-section-subtitle">Top Sources</div>
    {sources.map((s, i) => (
      <a
        key={i}
        href={s.url}
        target="_blank"
        rel="noopener noreferrer"
        className="research-sources-list__item"
      >
        <span className="research-sources-list__domain">{s.source_domain}</span>
        <span className="research-sources-list__title">{s.title}</span>
      </a>
    ))}
  </div>
);
