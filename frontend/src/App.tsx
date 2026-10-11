import React, { useState, useEffect } from 'react';
import {
  Search, ShieldCheck, AlertTriangle, ExternalLink, Download,
  CheckCircle2, XCircle, Clock, RefreshCw, Filter, Sparkles,
  Flag, Server, Layers, Terminal, ArrowRight, X
} from 'lucide-react';
import type { AppDetail, SearchResponse, VerificationCheck } from './types';

export default function App() {
  const [query, setQuery] = useState('music');
  const [platformFilter, setPlatformFilter] = useState<string>('');
  const [licenseFilter, setLicenseFilter] = useState<string>('');
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedAppSlug, setSelectedAppSlug] = useState<string | null>(null);
  const [appDetail, setAppDetail] = useState<AppDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [checkingUrl, setCheckingUrl] = useState(false);
  const [verificationFeedback, setVerificationFeedback] = useState<VerificationCheck | null>(null);

  // Correction Modal State
  const [correctionModalOpen, setCorrectionModalOpen] = useState(false);
  const [targetAppIdentifier, setTargetAppIdentifier] = useState('');
  const [correctionType, setCorrectionType] = useState<'correction' | 'removal'>('correction');
  const [correctionReason, setCorrectionReason] = useState('');
  const [correctionEmail, setCorrectionEmail] = useState('');
  const [correctionSubmitted, setCorrectionSubmitted] = useState(false);
  const [correctionSubmitting, setCorrectionSubmitting] = useState(false);

  // Operator Status State
  const [opsModalOpen, setOpsModalOpen] = useState(false);
  const [opsTokenInput, setOpsTokenInput] = useState('');
  const [opsData, setOpsData] = useState<any>(null);
  const [opsError, setOpsError] = useState('');

  // Initial search on mount
  useEffect(() => {
    handleSearch('music', platformFilter, licenseFilter);
  }, []);

  const handleSearch = async (searchQ: string, platform = platformFilter, license = licenseFilter) => {
    if (!searchQ.trim()) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ q: searchQ });
      if (platform) params.append('platform', platform);
      if (license) params.append('license_state', license);

      const res = await fetch(`/api/v1/search?${params.toString()}`);
      if (!res.ok) throw new Error('Search failed');
      const data: SearchResponse = await res.json();
      setSearchResponse(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenDetail = async (slug: string) => {
    setSelectedAppSlug(slug);
    setDetailLoading(true);
    setVerificationFeedback(null);
    try {
      const res = await fetch(`/api/v1/apps/${slug}`);
      if (!res.ok) throw new Error('Failed to fetch app');
      const data: AppDetail = await res.json();
      setAppDetail(data);
    } catch (err) {
      console.error(err);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleTriggerRealCheck = async (slug: string) => {
    setCheckingUrl(true);
    try {
      const res = await fetch(`/api/v1/apps/${slug}/verify`, { method: 'POST' });
      if (!res.ok) throw new Error('Check execution failed');
      const checkResult: VerificationCheck = await res.json();
      setVerificationFeedback(checkResult);
      // Refresh detail data
      const refreshRes = await fetch(`/api/v1/apps/${slug}`);
      if (refreshRes.ok) {
        const updated = await refreshRes.json();
        setAppDetail(updated);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setCheckingUrl(false);
    }
  };

  const submitCorrection = async (e: React.FormEvent) => {
    e.preventDefault();
    setCorrectionSubmitting(true);
    try {
      const res = await fetch('/api/v1/corrections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          app_identifier: targetAppIdentifier,
          request_type: correctionType,
          reason: correctionReason,
          contact_email: correctionEmail || undefined,
        }),
      });
      if (res.ok) {
        setCorrectionSubmitted(true);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setCorrectionSubmitting(false);
    }
  };

  const fetchOpsStatus = async () => {
    setOpsError('');
    setOpsData(null);
    try {
      const res = await fetch('/api/v1/ops/status', {
        headers: { Authorization: `Bearer ${opsTokenInput}` },
      });
      if (!res.ok) {
        if (res.status === 401 || res.status === 403) {
          throw new Error('Authentication rejected. Valid OPS_TOKEN required.');
        }
        throw new Error('Failed to retrieve ops status');
      }
      const data = await res.json();
      setOpsData(data);
    } catch (err: any) {
      setOpsError(err.message);
    }
  };

  const renderVerificationBadge = (status: string) => {
    switch (status) {
      case 'VERIFIED_RECENTLY':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium badge-verified">
            <CheckCircle2 className="w-3.5 h-3.5" />
            Verified Available
          </span>
        );
      case 'PARTIALLY_VERIFIED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium badge-partially">
            <Clock className="w-3.5 h-3.5" />
            Partially Verified
          </span>
        );
      case 'VERIFICATION_FAILED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium badge-failed">
            <XCircle className="w-3.5 h-3.5" />
            Verification Failed
          </span>
        );
      case 'STALE':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium badge-stale">
            <Clock className="w-3.5 h-3.5" />
            Check Stale (&gt;7d)
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-zinc-800 text-zinc-400 border border-zinc-700">
            <AlertTriangle className="w-3.5 h-3.5" />
            Unverified
          </span>
        );
    }
  };

  const samplePrompts = [
    'music',
    'storage',
    'organize my photos',
    'find duplicate audio files',
    'open-source photo editor for Linux',
    'encrypted cloud backup',
  ];

  return (
    <div className="min-h-screen bg-[#090a0f] text-slate-100 flex flex-col selection:bg-indigo-500/30">
      {/* Top Navigation */}
      <header className="border-b border-zinc-800/80 bg-zinc-950/70 backdrop-blur-md sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <ShieldCheck className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-zinc-200 to-zinc-400 bg-clip-text text-transparent">
                OSS Discovery
              </span>
              <span className="hidden sm:inline-block ml-2 px-2 py-0.5 text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-md">
                Trustworthy Catalog
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 sm:gap-4">
            <button
              id="open-ops-btn"
              onClick={() => setOpsModalOpen(true)}
              className="px-3 py-1.5 text-xs font-medium text-zinc-400 hover:text-white bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 rounded-lg flex items-center gap-1.5 transition-colors"
            >
              <Server className="w-3.5 h-3.5 text-indigo-400" />
              <span>Operations</span>
            </button>
            <button
              id="open-correction-btn"
              onClick={() => {
                setTargetAppIdentifier('');
                setCorrectionSubmitted(false);
                setCorrectionModalOpen(true);
              }}
              className="px-3 py-1.5 text-xs font-medium text-zinc-400 hover:text-white bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 rounded-lg flex items-center gap-1.5 transition-colors"
            >
              <Flag className="w-3.5 h-3.5 text-rose-400" />
              <span>Correction / Removal</span>
            </button>
          </div>
        </div>
      </header>

      {/* Hero & Search Header */}
      <section className="relative pt-12 pb-8 px-4 sm:px-6 max-w-5xl mx-auto w-full text-center">
        <div className="absolute inset-x-0 -top-10 h-72 bg-gradient-to-b from-indigo-500/10 via-purple-500/5 to-transparent blur-3xl pointer-events-none" />

        <h1 className="text-3xl sm:text-5xl font-extrabold tracking-tight text-white mb-4">
          Discover Verified <span className="gradient-brand">Open-Source</span> Software
        </h1>
        <p className="text-base sm:text-lg text-zinc-400 max-w-2xl mx-auto mb-8 font-normal">
          Type what you want to accomplish. We interpret tasks, match documented capabilities, and independently verify external availability.
        </p>

        {/* Search Input Box */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSearch(query);
          }}
          className="relative max-w-3xl mx-auto mb-5"
        >
          <div className="relative flex items-center">
            <Search className="w-5 h-5 text-indigo-400 absolute left-4 pointer-events-none" />
            <input
              id="search-input"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="E.g., organize my photos, audio editor, storage cleanup..."
              className="w-full pl-12 pr-28 py-4 bg-zinc-900/90 border border-zinc-700/80 hover:border-zinc-600 focus:border-indigo-500 rounded-2xl text-white placeholder-zinc-500 shadow-2xl focus:outline-none focus:ring-4 focus:ring-indigo-500/10 transition-all text-base"
            />
            <button
              id="search-submit-btn"
              type="submit"
              disabled={loading}
              className="absolute right-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-white rounded-xl font-medium text-sm transition-all shadow-md flex items-center gap-2"
            >
              {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              <span>Search</span>
            </button>
          </div>
        </form>

        {/* Quick Suggestion Pills */}
        <div className="flex flex-wrap items-center justify-center gap-2 max-w-3xl mx-auto mb-6">
          <span className="text-xs text-zinc-500 mr-1 flex items-center gap-1">
            <Terminal className="w-3 h-3" /> Examples:
          </span>
          {samplePrompts.map((prompt) => (
            <button
              key={prompt}
              id={`example-prompt-${prompt.replace(/\s+/g, '-')}`}
              onClick={() => {
                setQuery(prompt);
                handleSearch(prompt);
              }}
              className="text-xs px-3 py-1.5 rounded-full bg-zinc-900/80 hover:bg-zinc-800 text-zinc-300 hover:text-white border border-zinc-800 transition-colors"
            >
              {prompt}
            </button>
          ))}
        </div>

        {/* Filter Bar */}
        <div className="flex flex-wrap items-center justify-center gap-3 pt-3 border-t border-zinc-800/60 max-w-3xl mx-auto text-xs">
          <div className="flex items-center gap-1.5 text-zinc-400 font-medium">
            <Filter className="w-3.5 h-3.5" /> Platform:
          </div>
          {['', 'linux', 'windows', 'macos', 'web'].map((p) => (
            <button
              key={p}
              id={`filter-platform-${p || 'all'}`}
              onClick={() => {
                setPlatformFilter(p);
                handleSearch(query, p, licenseFilter);
              }}
              className={`px-3 py-1 rounded-lg border transition-all ${
                platformFilter === p
                  ? 'bg-indigo-600/20 text-indigo-300 border-indigo-500/40 font-medium'
                  : 'bg-zinc-900/50 text-zinc-400 border-zinc-800 hover:text-zinc-200'
              }`}
            >
              {p ? p.toUpperCase() : 'All'}
            </button>
          ))}

          <div className="flex items-center gap-1.5 text-zinc-400 font-medium ml-2 sm:ml-4">
            License:
          </div>
          {['', 'confirmed_open_source'].map((l) => (
            <button
              key={l}
              id={`filter-license-${l || 'all'}`}
              onClick={() => {
                setLicenseFilter(l);
                handleSearch(query, platformFilter, l);
              }}
              className={`px-3 py-1 rounded-lg border transition-all ${
                licenseFilter === l
                  ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500/40 font-medium'
                  : 'bg-zinc-900/50 text-zinc-400 border-zinc-800 hover:text-zinc-200'
              }`}
            >
              {l ? 'Confirmed FOSS' : 'All'}
            </button>
          ))}
        </div>
      </section>

      {/* Main Content Area: Results */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6 w-full flex-1">
        {searchResponse && (
          <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-zinc-800/80 pb-4">
            <div className="flex items-center gap-2">
              <span className="text-sm text-zinc-400">
                Found <strong className="text-white">{searchResponse.total_results}</strong> application{searchResponse.total_results === 1 ? '' : 's'} for:
              </span>
              <span className="text-xs px-2.5 py-1 bg-zinc-800 text-zinc-200 rounded-md font-mono">
                "{searchResponse.query}"
              </span>
              {searchResponse.detected_categories.length > 0 && (
                <div className="hidden sm:flex items-center gap-1.5 ml-2">
                  <span className="text-xs text-zinc-500">Taxonomy:</span>
                  {searchResponse.detected_categories.map((c) => (
                    <span key={c} className="text-xs px-2 py-0.5 bg-indigo-950/60 text-indigo-300 border border-indigo-800/50 rounded-md">
                      {c}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="text-xs text-zinc-500">
              Deterministic RRF Ranking + Stored Verification Checks
            </div>
          </div>
        )}

        {/* Loading State */}
        {loading && (
          <div className="py-20 text-center flex flex-col items-center justify-center">
            <RefreshCw className="w-8 h-8 text-indigo-400 animate-spin mb-4" />
            <p className="text-zinc-400 text-sm">Searching verified open-source database...</p>
          </div>
        )}

        {/* Empty State with Honest Fallback and Category Suggestions */}
        {!loading && searchResponse && searchResponse.results.length === 0 && (
          <div className="py-16 px-6 text-center max-w-xl mx-auto glass-panel rounded-2xl border border-zinc-800">
            <div className="w-12 h-12 rounded-full bg-zinc-800 flex items-center justify-center mx-auto mb-4 text-zinc-400">
              <AlertTriangle className="w-6 h-6 text-amber-400" />
            </div>
            <h3 className="text-lg font-bold text-white mb-2">No Verified Applications Found</h3>
            <p className="text-zinc-400 text-sm mb-6 leading-relaxed">
              We did not find qualified open-source applications matching <span className="text-zinc-200 font-mono">"{searchResponse.query}"</span>. We do not fabricate results.
            </p>
            {searchResponse.suggested_categories.length > 0 && (
              <div>
                <p className="text-xs text-zinc-500 uppercase tracking-wider font-semibold mb-3">
                  Explore known catalog categories:
                </p>
                <div className="flex flex-wrap justify-center gap-2">
                  {searchResponse.suggested_categories.map((cat) => (
                    <button
                      key={cat.slug}
                      onClick={() => {
                        setQuery(cat.name);
                        handleSearch(cat.name);
                      }}
                      className="text-xs px-3 py-1.5 bg-zinc-900 hover:bg-zinc-800 text-indigo-300 border border-zinc-700/80 rounded-lg transition-colors"
                    >
                      {cat.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Results Grid */}
        {!loading && searchResponse && searchResponse.results.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {searchResponse.results.map((app) => (
              <div
                key={app.id}
                id={`app-card-${app.slug}`}
                className="glass-card rounded-2xl p-6 flex flex-col justify-between border border-zinc-800 hover:border-zinc-700"
              >
                <div>
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div>
                      <h3 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
                        {app.name}
                      </h3>
                      {app.primary_category && (
                        <span className="text-xs text-indigo-400 font-medium">
                          {app.primary_category.name}
                        </span>
                      )}
                    </div>
                    {renderVerificationBadge(app.verification_status)}
                  </div>

                  <p className="text-zinc-300 text-sm mb-4 line-clamp-3 leading-relaxed">
                    {app.summary}
                  </p>

                  {/* Capabilities Tags */}
                  <div className="flex flex-wrap gap-1.5 mb-4">
                    {app.capabilities.slice(0, 3).map((cap) => (
                      <span
                        key={cap}
                        className="text-[11px] px-2.5 py-1 bg-zinc-800/80 text-zinc-300 rounded-md border border-zinc-700/50"
                      >
                        {cap}
                      </span>
                    ))}
                    {app.capabilities.length > 3 && (
                      <span className="text-[11px] px-2 py-1 bg-zinc-900 text-zinc-500 rounded-md">
                        +{app.capabilities.length - 3} more
                      </span>
                    )}
                  </div>

                  {/* Platform & License Badges */}
                  <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-zinc-800/80 text-[11px] text-zinc-400">
                    <span className="font-mono bg-zinc-900 px-2 py-0.5 rounded text-emerald-400 border border-emerald-900/30">
                      {app.license_spdx || 'Open Source'}
                    </span>
                    <span className="capitalize">
                      {app.platforms.join(', ')}
                    </span>
                  </div>
                </div>

                {/* Card Actions */}
                <div className="mt-6 pt-4 border-t border-zinc-800/80 flex items-center justify-between gap-3">
                  <a
                    id={`official-link-${app.slug}`}
                    href={app.homepage_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-xs text-zinc-300 hover:text-white hover:underline transition-all"
                  >
                    <span>Website</span>
                    <ExternalLink className="w-3 h-3 text-zinc-400" />
                  </a>

                  <button
                    id={`view-details-${app.slug}`}
                    onClick={() => handleOpenDetail(app.slug)}
                    className="px-4 py-2 bg-zinc-800 hover:bg-indigo-600 hover:text-white text-zinc-200 rounded-xl text-xs font-semibold transition-all flex items-center gap-1.5"
                  >
                    <span>Details &amp; Audit</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Application Detail Modal */}
      {selectedAppSlug && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 overflow-y-auto">
          <div
            id="app-detail-modal"
            className="bg-zinc-950 border border-zinc-800 rounded-3xl max-w-3xl w-full p-6 sm:p-8 max-h-[90vh] overflow-y-auto relative shadow-2xl"
          >
            <button
              id="close-detail-modal"
              onClick={() => setSelectedAppSlug(null)}
              className="absolute top-6 right-6 text-zinc-400 hover:text-white bg-zinc-900 p-2 rounded-full border border-zinc-800 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>

            {detailLoading || !appDetail ? (
              <div className="py-20 text-center flex flex-col items-center justify-center">
                <RefreshCw className="w-8 h-8 text-indigo-400 animate-spin mb-3" />
                <p className="text-zinc-400 text-sm">Loading verified application profile...</p>
              </div>
            ) : (
              <div>
                {/* Header */}
                <div className="flex flex-wrap items-start justify-between gap-4 mb-4 pr-8">
                  <div>
                    <h2 className="text-2xl sm:text-3xl font-extrabold text-white">
                      {appDetail.name}
                    </h2>
                    <div className="flex flex-wrap items-center gap-2 mt-2">
                      {appDetail.primary_category && (
                        <span className="text-xs px-2.5 py-1 bg-indigo-950/80 text-indigo-300 border border-indigo-800/50 rounded-md font-medium">
                          {appDetail.primary_category.name}
                        </span>
                      )}
                      <span className="text-xs px-2.5 py-1 bg-emerald-950/80 text-emerald-300 border border-emerald-800/50 rounded-md font-mono">
                        {appDetail.license_spdx || 'FOSS'}
                      </span>
                      <span className="text-xs text-zinc-400">
                        Platforms: {appDetail.platforms.join(', ')}
                      </span>
                    </div>
                  </div>
                  <div>
                    {renderVerificationBadge(appDetail.verification_summary.overall_status)}
                  </div>
                </div>

                <p className="text-zinc-300 text-sm sm:text-base leading-relaxed mb-6">
                  {appDetail.description}
                </p>

                {/* Validated Links Row */}
                <div className="flex flex-wrap gap-3 mb-8">
                  <a
                    id="modal-official-website-link"
                    href={appDetail.homepage_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold flex items-center gap-2 shadow-lg shadow-indigo-600/20 transition-all"
                  >
                    <span>Official Website</span>
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>

                  {appDetail.repo_url && (
                    <a
                      id="modal-repo-link"
                      href={appDetail.repo_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-4 py-2.5 bg-zinc-900 hover:bg-zinc-800 text-zinc-200 border border-zinc-700/80 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all"
                    >
                      <span>Source Repository</span>
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  )}

                  <button
                    id="trigger-live-check-btn"
                    onClick={() => handleTriggerRealCheck(appDetail.slug)}
                    disabled={checkingUrl}
                    className="px-4 py-2.5 bg-zinc-900 hover:bg-zinc-800 text-emerald-400 border border-emerald-800/40 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all ml-auto"
                  >
                    {checkingUrl ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                    <span>Run Real Check Now</span>
                  </button>
                </div>

                {/* Stored Verification Audit Panel */}
                <div className="bg-zinc-900/90 rounded-2xl p-5 border border-zinc-800 mb-8">
                  <div className="flex items-center justify-between mb-4">
                    <h4 className="text-sm font-bold text-white flex items-center gap-2">
                      <ShieldCheck className="w-4 h-4 text-emerald-400" />
                      Transparent Verification Evidence
                    </h4>
                    <span className="text-[11px] text-zinc-500">
                      Independent Evidence &bull; No Synthetic Claims
                    </span>
                  </div>

                  {/* Verification Status Badges Row */}
                  <div className="flex flex-wrap gap-2 mb-4">
                    {appDetail.verification_summary.website_check?.status === 'SUCCESS' ? (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] bg-emerald-950/60 text-emerald-300 border border-emerald-800/40">
                        <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                        Website Reachable
                      </span>
                    ) : appDetail.verification_summary.website_check ? (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] bg-rose-950/60 text-rose-300 border border-rose-800/40">
                        <XCircle className="w-3 h-3 text-rose-400" />
                        Website Check Failed
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] bg-zinc-800 text-zinc-400 border border-zinc-700">
                        Website Unchecked
                      </span>
                    )}

                    {appDetail.releases.length > 0 ? (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] bg-indigo-950/60 text-indigo-300 border border-indigo-800/40">
                        <Download className="w-3 h-3 text-indigo-400" />
                        Official Release Available ({appDetail.releases.length})
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] bg-zinc-900 text-zinc-400 border border-zinc-800">
                        Download Information Unavailable
                      </span>
                    )}

                    {appDetail.verification_summary.release_check?.status === 'SUCCESS' ? (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] bg-violet-950/60 text-violet-300 border border-violet-800/40">
                        <RefreshCw className="w-3 h-3 text-violet-400" />
                        Metadata Recently Synchronized
                      </span>
                    ) : null}

                    {appDetail.verification_summary.overall_status === 'STALE' && (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] bg-amber-950/60 text-amber-300 border border-amber-800/40">
                        <Clock className="w-3 h-3 text-amber-400" />
                        Evidence Stale (&gt;7d Website / &gt;30d Repo)
                      </span>
                    )}
                  </div>

                  {/* Website Verification Metric Cards */}
                  {appDetail.verification_summary.website_check && (
                    <div className="mb-3">
                      <div className="text-[11px] font-semibold text-zinc-400 mb-1.5 flex items-center justify-between">
                        <span>Official Website Check</span>
                        <span className="text-zinc-500 font-mono text-[10px]">
                          Checked: {new Date(appDetail.verification_summary.website_check.checked_at).toLocaleString()}
                        </span>
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-zinc-950/60 p-3 rounded-xl border border-zinc-800/60 font-mono text-xs">
                        <div>
                          <div className="text-zinc-500 text-[10px]">HTTP STATUS</div>
                          <div className={appDetail.verification_summary.website_check.status === 'SUCCESS' ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}>
                            {appDetail.verification_summary.website_check.http_status || 'Connection Error'}
                          </div>
                        </div>
                        <div>
                          <div className="text-zinc-500 text-[10px]">TLS VALID</div>
                          <div className={appDetail.verification_summary.website_check.tls_valid ? 'text-emerald-400' : 'text-amber-400'}>
                            {appDetail.verification_summary.website_check.tls_valid ? 'Yes (HTTPS)' : 'No'}
                          </div>
                        </div>
                        <div>
                          <div className="text-zinc-500 text-[10px]">LATENCY</div>
                          <div className="text-white">
                            {appDetail.verification_summary.website_check.duration_ms ? `${appDetail.verification_summary.website_check.duration_ms} ms` : 'N/A'}
                          </div>
                        </div>
                        <div>
                          <div className="text-zinc-500 text-[10px]">DESTINATION</div>
                          <div className="text-zinc-400 text-[11px] truncate" title={appDetail.verification_summary.website_check.final_url || appDetail.homepage_url}>
                            {new URL(appDetail.verification_summary.website_check.final_url || appDetail.homepage_url).hostname}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Release Metadata Sync Metric Cards */}
                  {appDetail.verification_summary.release_check && (
                    <div className="mb-3">
                      <div className="text-[11px] font-semibold text-zinc-400 mb-1.5 flex items-center justify-between">
                        <span>Official Release Synchronization</span>
                        <span className="text-zinc-500 font-mono text-[10px]">
                          Synced: {new Date(appDetail.verification_summary.release_check.checked_at).toLocaleString()}
                        </span>
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 bg-zinc-950/60 p-3 rounded-xl border border-zinc-800/60 font-mono text-xs">
                        <div>
                          <div className="text-zinc-500 text-[10px]">SYNC STATUS</div>
                          <div className={appDetail.verification_summary.release_check.status === 'SUCCESS' ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}>
                            {appDetail.verification_summary.release_check.status}
                          </div>
                        </div>
                        <div>
                          <div className="text-zinc-500 text-[10px]">RELEASES SYNCED</div>
                          <div className="text-white font-bold">
                            {appDetail.verification_summary.release_check.details?.releases_synced ?? appDetail.releases.length}
                          </div>
                        </div>
                        <div>
                          <div className="text-zinc-500 text-[10px]">SOURCE</div>
                          <div className="text-zinc-300 text-[11px] truncate">
                            {appDetail.repo_url ? 'GitHub Releases API' : 'Direct Catalog'}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {appDetail.verification_summary.website_check?.error_message && (
                    <div className="p-3 bg-rose-950/40 text-rose-300 border border-rose-800/60 rounded-xl text-xs flex items-center gap-2 mb-2">
                      <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                      <span>Sanitized Failure Detail: {appDetail.verification_summary.website_check.error_message}</span>
                    </div>
                  )}

                  {verificationFeedback && (
                    <div className="mt-3 p-3 bg-emerald-950/40 border border-emerald-800/60 rounded-xl text-xs text-emerald-300 flex items-center gap-2 animate-fadeIn">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                      <span>Live check completed: HTTP {verificationFeedback.http_status || 'Done'} ({verificationFeedback.duration_ms}ms). Stored to database.</span>
                    </div>
                  )}
                </div>

                {/* Capabilities List */}
                <div className="mb-8">
                  <h4 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                    <Layers className="w-4 h-4 text-indigo-400" /> Documented Capabilities
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {appDetail.capabilities.map((c, i) => (
                      <div key={i} className="p-3 bg-zinc-900/60 border border-zinc-800/80 rounded-xl">
                        <div className="font-semibold text-xs text-white mb-1">
                          {c.capability}
                        </div>
                        {c.detail && (
                          <div className="text-[11px] text-zinc-400 leading-normal">
                            {c.detail}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Releases & Official Downloads */}
                <div className="mb-8">
                  <h4 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                    <Download className="w-4 h-4 text-indigo-400" /> Official Releases &amp; Downloads
                  </h4>

                  {appDetail.releases.length > 0 ? (
                    <div className="space-y-4">
                      {appDetail.releases.map((rel) => (
                        <div key={rel.id} className="p-4 bg-zinc-900/70 border border-zinc-800 rounded-xl">
                          <div className="flex flex-wrap items-center justify-between gap-2 mb-2 pb-2 border-b border-zinc-800/60">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-sm text-white">
                                {rel.name || rel.tag_name}
                              </span>
                              <span className="font-mono text-[11px] px-2 py-0.5 bg-zinc-800 text-zinc-300 rounded border border-zinc-700">
                                {rel.tag_name}
                              </span>
                              {rel.is_prerelease && (
                                <span className="text-[10px] px-1.5 py-0.5 bg-amber-950 text-amber-300 rounded border border-amber-800">
                                  Pre-release
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-3 text-xs text-zinc-400">
                              {rel.published_at && (
                                <span>Published: {new Date(rel.published_at).toLocaleDateString()}</span>
                              )}
                              <a
                                href={rel.release_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-indigo-400 hover:text-indigo-300 inline-flex items-center gap-1 font-medium"
                              >
                                <span>Release Notes</span>
                                <ExternalLink className="w-3 h-3" />
                              </a>
                            </div>
                          </div>

                          {rel.assets.length > 0 ? (
                            <div className="space-y-2 mt-3">
                              {rel.assets.map((asset) => (
                                <div key={asset.id} className="flex flex-wrap items-center justify-between gap-2 p-2.5 bg-zinc-950/80 rounded-lg text-xs border border-zinc-850">
                                  <div className="flex items-center gap-2 min-w-0">
                                    {asset.platform && (
                                      <span className="uppercase text-[9px] font-bold px-1.5 py-0.5 bg-zinc-800 text-zinc-300 rounded">
                                        {asset.platform}
                                      </span>
                                    )}
                                    <span className="font-mono text-zinc-200 truncate max-w-[220px] sm:max-w-md">
                                      {asset.name}
                                    </span>
                                  </div>
                                  <div className="flex items-center gap-3 shrink-0">
                                    {asset.checksum && (
                                      <span className="text-[10px] text-zinc-500 font-mono hidden sm:inline" title={asset.checksum}>
                                        {asset.checksum_algorithm ? asset.checksum_algorithm.toUpperCase() : 'HASH'}: {asset.checksum.slice(0, 8)}...
                                      </span>
                                    )}
                                    {asset.size_bytes && (
                                      <span className="text-zinc-500 text-[11px]">
                                        {(asset.size_bytes / (1024 * 1024)).toFixed(1)} MB
                                      </span>
                                    )}
                                    {asset.is_reachable !== undefined && (
                                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${asset.is_reachable ? 'bg-emerald-950/50 text-emerald-400' : 'bg-zinc-900 text-zinc-500'}`}>
                                        {asset.is_reachable ? 'Reachable' : 'Unchecked'}
                                      </span>
                                    )}
                                    <a
                                      href={asset.download_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="px-3 py-1 bg-indigo-600/30 hover:bg-indigo-600 text-indigo-300 hover:text-white rounded-md text-[11px] font-semibold transition-colors flex items-center gap-1.5"
                                    >
                                      <span>Official Download</span>
                                      <Download className="w-3 h-3" />
                                    </a>
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="p-3 bg-zinc-950/50 rounded-lg text-xs text-zinc-400 italic">
                              No standalone binary assets published for this release (source code distribution only).
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="p-4 bg-zinc-900/40 border border-zinc-800 rounded-xl text-xs text-zinc-400">
                      <p className="font-medium text-zinc-300 mb-1">Download Information Unavailable</p>
                      <p className="text-zinc-500">
                        No official pre-compiled releases have been synchronized from the upstream repository. Please refer to the official website or repository for installation directions.
                      </p>
                    </div>
                  )}
                </div>

                {/* Footer action: Report takedown/correction */}
                <div className="pt-4 border-t border-zinc-800 flex justify-end">
                  <button
                    onClick={() => {
                      setTargetAppIdentifier(appDetail.slug);
                      setCorrectionSubmitted(false);
                      setCorrectionModalOpen(true);
                    }}
                    className="text-xs text-rose-400 hover:text-rose-300 flex items-center gap-1.5 transition-colors"
                  >
                    <Flag className="w-3.5 h-3.5" />
                    <span>Report inaccuracy or request removal for {appDetail.name}</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Public Correction / Takedown Request Modal */}
      {correctionModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-zinc-950 border border-zinc-800 rounded-3xl max-w-lg w-full p-6 sm:p-8 relative shadow-2xl">
            <button
              onClick={() => setCorrectionModalOpen(false)}
              className="absolute top-6 right-6 text-zinc-400 hover:text-white bg-zinc-900 p-2 rounded-full border border-zinc-800 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>

            <h3 className="text-xl font-bold text-white mb-2 flex items-center gap-2">
              <Flag className="w-5 h-5 text-rose-400" />
              Correction or Takedown Request
            </h3>
            <p className="text-xs text-zinc-400 mb-6 leading-relaxed">
              We uphold trustworthy software discovery. Operators review each request before modifying or delisting applications.
            </p>

            {correctionSubmitted ? (
              <div className="py-8 text-center">
                <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
                <h4 className="text-base font-bold text-white mb-1">Request Recorded</h4>
                <p className="text-xs text-zinc-400">
                  Your request has been submitted with a pending status. It will be reviewed by an operator in accordance with the audit guidelines.
                </p>
                <button
                  onClick={() => setCorrectionModalOpen(false)}
                  className="mt-6 px-5 py-2 bg-zinc-800 hover:bg-zinc-700 text-white rounded-xl text-xs font-semibold"
                >
                  Close
                </button>
              </div>
            ) : (
              <form onSubmit={submitCorrection} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-zinc-300 mb-1">
                    Application URL or Identifier *
                  </label>
                  <input
                    type="text"
                    required
                    value={targetAppIdentifier}
                    onChange={(e) => setTargetAppIdentifier(e.target.value)}
                    placeholder="e.g. audacity, or https://example.com"
                    className="w-full px-3.5 py-2.5 bg-zinc-900 border border-zinc-800 rounded-xl text-white text-xs focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-zinc-300 mb-1">
                    Request Type *
                  </label>
                  <div className="flex gap-4 text-xs">
                    <label className="flex items-center gap-2 text-zinc-300 cursor-pointer">
                      <input
                        type="radio"
                        name="reqType"
                        value="correction"
                        checked={correctionType === 'correction'}
                        onChange={() => setCorrectionType('correction')}
                      />
                      <span>Metadata Correction</span>
                    </label>
                    <label className="flex items-center gap-2 text-zinc-300 cursor-pointer">
                      <input
                        type="radio"
                        name="reqType"
                        value="removal"
                        checked={correctionType === 'removal'}
                        onChange={() => setCorrectionType('removal')}
                      />
                      <span>Takedown / Removal</span>
                    </label>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-zinc-300 mb-1">
                    Reason &amp; Evidence *
                  </label>
                  <textarea
                    required
                    rows={4}
                    value={correctionReason}
                    onChange={(e) => setCorrectionReason(e.target.value)}
                    placeholder="Describe inaccuracy, licensing discrepancy, or takedown grounds..."
                    className="w-full px-3.5 py-2.5 bg-zinc-900 border border-zinc-800 rounded-xl text-white text-xs focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-zinc-300 mb-1">
                    Contact Email (Optional)
                  </label>
                  <input
                    type="email"
                    value={correctionEmail}
                    onChange={(e) => setCorrectionEmail(e.target.value)}
                    placeholder="your@email.com"
                    className="w-full px-3.5 py-2.5 bg-zinc-900 border border-zinc-800 rounded-xl text-white text-xs focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div className="pt-2 flex justify-end gap-3">
                  <button
                    type="button"
                    onClick={() => setCorrectionModalOpen(false)}
                    className="px-4 py-2 bg-zinc-900 text-zinc-400 hover:text-white rounded-xl text-xs font-semibold"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={correctionSubmitting}
                    className="px-5 py-2 bg-rose-600 hover:bg-rose-500 text-white rounded-xl text-xs font-semibold flex items-center gap-2"
                  >
                    {correctionSubmitting && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                    <span>Submit Request</span>
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* Operator Status Modal */}
      {opsModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-zinc-950 border border-zinc-800 rounded-3xl max-w-xl w-full p-6 sm:p-8 relative shadow-2xl">
            <button
              onClick={() => setOpsModalOpen(false)}
              className="absolute top-6 right-6 text-zinc-400 hover:text-white bg-zinc-900 p-2 rounded-full border border-zinc-800 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>

            <h3 className="text-xl font-bold text-white mb-2 flex items-center gap-2">
              <Server className="w-5 h-5 text-indigo-400" />
              Operator System Visibility
            </h3>
            <p className="text-xs text-zinc-400 mb-6 leading-relaxed">
              Protected operations endpoint. Supply environment OPS_TOKEN to view background worker status and pending audit items.
            </p>

            <div className="flex gap-2 mb-6">
              <input
                id="ops-token-input"
                type="password"
                value={opsTokenInput}
                onChange={(e) => setOpsTokenInput(e.target.value)}
                placeholder="Enter OPS_TOKEN..."
                className="flex-1 px-3.5 py-2.5 bg-zinc-900 border border-zinc-800 rounded-xl text-white text-xs focus:outline-none focus:border-indigo-500"
              />
              <button
                id="ops-token-submit-btn"
                onClick={fetchOpsStatus}
                className="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold"
              >
                Authenticate
              </button>
            </div>

            {opsError && (
              <div className="p-3 bg-rose-950/40 text-rose-300 border border-rose-800/60 rounded-xl text-xs mb-4 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                <span>{opsError}</span>
              </div>
            )}

            {opsData && (
              <div className="space-y-4 text-xs font-mono max-h-[60vh] overflow-y-auto pr-1">
                <div className="grid grid-cols-2 gap-3 bg-zinc-900/80 p-4 rounded-xl border border-zinc-800">
                  <div>
                    <div className="text-zinc-500 text-[10px]">WORKER STATUS</div>
                    <div className="text-emerald-400 font-bold">{opsData.worker_status}</div>
                  </div>
                  <div>
                    <div className="text-zinc-500 text-[10px]">PENDING CORRECTIONS</div>
                    <div className="text-white font-bold">{opsData.pending_corrections_count}</div>
                  </div>
                  <div>
                    <div className="text-zinc-500 text-[10px]">TOTAL APPLICATIONS</div>
                    <div className="text-white font-bold">{opsData.total_apps}</div>
                  </div>
                  <div>
                    <div className="text-zinc-500 text-[10px]">TOTAL VERIFICATION CHECKS</div>
                    <div className="text-white font-bold">{opsData.total_checks}</div>
                  </div>
                </div>

                {/* Scheduler Telemetry */}
                <div className="bg-zinc-900/80 p-4 rounded-xl border border-zinc-800">
                  <div className="text-zinc-300 font-bold mb-2 flex items-center justify-between">
                    <span>Scheduler &amp; Verification Health</span>
                    <span className="text-zinc-500 text-[10px]">Periodic Cycle: 24h</span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
                    <div className="bg-zinc-950/60 p-2 rounded">
                      <div className="text-zinc-500 text-[9px]">PENDING JOBS</div>
                      <div className="text-indigo-400 font-bold">{opsData.pending_jobs ?? 0}</div>
                    </div>
                    <div className="bg-zinc-950/60 p-2 rounded">
                      <div className="text-zinc-500 text-[9px]">RUNNING JOBS</div>
                      <div className="text-amber-400 font-bold">{opsData.running_jobs ?? 0}</div>
                    </div>
                    <div className="bg-zinc-950/60 p-2 rounded">
                      <div className="text-zinc-500 text-[9px]">FAILED JOBS</div>
                      <div className={(opsData.failed_jobs ?? 0) > 0 ? "text-rose-400 font-bold" : "text-zinc-400 font-bold"}>
                        {opsData.failed_jobs ?? 0}
                      </div>
                    </div>
                    <div className="bg-zinc-950/60 p-2 rounded">
                      <div className="text-zinc-500 text-[9px]">STALE APPS</div>
                      <div className={(opsData.stale_apps_count ?? 0) > 0 ? "text-amber-400 font-bold" : "text-emerald-400 font-bold"}>
                        {opsData.stale_apps_count ?? 0}
                      </div>
                    </div>
                  </div>
                  <div className="text-[11px] space-y-1 text-zinc-400">
                    <div>
                      <span className="text-zinc-500">Last Scheduler Cycle: </span>
                      <span className="text-zinc-200">{opsData.last_scheduler_cycle ? new Date(opsData.last_scheduler_cycle).toLocaleString() : 'Pending first cycle'}</span>
                    </div>
                    <div>
                      <span className="text-zinc-500">Next Expected Cycle: </span>
                      <span className="text-zinc-200">{opsData.next_expected_cycle ? new Date(opsData.next_expected_cycle).toLocaleString() : 'Immediate upon worker execution'}</span>
                    </div>
                    <div>
                      <span className="text-zinc-500">Latest Release Sync: </span>
                      <span className="text-zinc-200">{opsData.most_recent_successful_sync ? new Date(opsData.most_recent_successful_sync).toLocaleString() : 'None completed yet'}</span>
                    </div>
                    {opsData.most_recent_sync_failure && (
                      <div className="text-rose-400">
                        <span className="text-rose-500">Latest Sync Failure: </span>
                        <span>{opsData.most_recent_sync_failure}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Semantic Encoder Diagnostics */}
                {opsData.encoder_diagnostics && (
                  <div className="bg-zinc-900/80 p-4 rounded-xl border border-zinc-800">
                    <div className="text-zinc-300 font-bold mb-2 flex items-center justify-between">
                      <span>Search &amp; Encoder Diagnostics</span>
                      <span className={`text-[10px] px-2 py-0.5 rounded font-semibold ${opsData.encoder_diagnostics.is_genuine_neural ? "bg-emerald-950 text-emerald-400" : "bg-zinc-800 text-zinc-400"}`}>
                        {opsData.encoder_diagnostics.is_genuine_neural ? "Genuine Neural Semantic" : "Deterministic Testing Hash"}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-[11px]">
                      <div>
                        <span className="text-zinc-500">Model: </span>
                        <span className="text-white">{opsData.encoder_diagnostics.model_name}</span>
                      </div>
                      <div>
                        <span className="text-zinc-500">Dimensions: </span>
                        <span className="text-white">{opsData.encoder_diagnostics.dimensions}</span>
                      </div>
                      <div>
                        <span className="text-zinc-500">Status: </span>
                        <span className="text-emerald-400">{opsData.encoder_diagnostics.status}</span>
                      </div>
                      <div>
                        <span className="text-zinc-500">Neural Embeddings: </span>
                        <span className="text-white">{String(opsData.encoder_diagnostics.is_genuine_neural)}</span>
                      </div>
                    </div>
                  </div>
                )}

                {opsData.checks_by_status && (
                  <div className="bg-zinc-900/80 p-4 rounded-xl border border-zinc-800">
                    <div className="text-zinc-400 font-semibold mb-2">Checks Breakdown</div>
                    <div className="flex gap-4">
                      {Object.entries(opsData.checks_by_status).map(([k, v]) => (
                        <div key={k}>
                          <span className="text-zinc-500">{k}: </span>
                          <span className="text-white font-bold">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="border-t border-zinc-800/80 bg-zinc-950/60 py-6 text-center text-xs text-zinc-500 mt-auto">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div>
            Open-Source Software Discovery Engine &bull; Stage 1A Walking Skeleton
          </div>
          <div className="flex items-center gap-4 text-zinc-400">
            <span>Deterministic RRF Search</span>
            <span>&bull;</span>
            <span>SSRF-Protected Verification</span>
            <span>&bull;</span>
            <span>No Hallucinated Software</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
