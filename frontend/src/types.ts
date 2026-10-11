export interface Category {
  id: number;
  slug: string;
  name: string;
  description?: string;
  parent_id?: number | null;
}

export interface VerificationCheck {
  id: number;
  check_type: string;
  status: 'SUCCESS' | 'FAILED' | 'SKIPPED';
  duration_ms?: number;
  checked_at: string;
  http_status?: number;
  final_url?: string;
  tls_valid?: boolean;
  details?: Record<string, any>;
  error_message?: string;
}

export interface VerificationSummary {
  overall_status: 'VERIFIED_RECENTLY' | 'PARTIALLY_VERIFIED' | 'VERIFICATION_FAILED' | 'STALE' | 'UNVERIFIED';
  website_check?: VerificationCheck;
  repo_check?: VerificationCheck;
  release_check?: VerificationCheck;
  all_checks: VerificationCheck[];
}

export interface ReleaseAsset {
  id: number;
  name: string;
  download_url: string;
  size_bytes?: number;
  checksum?: string;
  checksum_algorithm?: string;
  content_type?: string;
  platform?: string;
  is_reachable?: boolean;
  last_checked_at?: string;
}

export interface Release {
  id: number;
  tag_name: string;
  name?: string;
  published_at?: string;
  release_url: string;
  is_prerelease: boolean;
  source_commit?: string;
  last_synced_at?: string;
  assets: ReleaseAsset[];
}

export interface AppCapability {
  capability: string;
  detail?: string;
}

export interface AppListItem {
  id: number;
  slug: string;
  name: string;
  summary: string;
  homepage_url: string;
  repo_url?: string;
  license_state: string;
  license_spdx?: string;
  platforms: string[];
  primary_category?: Category;
  capabilities: string[];
  verification_status: 'VERIFIED_RECENTLY' | 'PARTIALLY_VERIFIED' | 'VERIFICATION_FAILED' | 'STALE' | 'UNVERIFIED';
  latest_check_at?: string;
  score?: number;
  match_sources: string[];
}

export interface AppDetail {
  id: number;
  slug: string;
  name: string;
  summary: string;
  description: string;
  homepage_url: string;
  repo_url?: string;
  license_state: string;
  license_spdx?: string;
  platforms: string[];
  is_delisted: boolean;
  primary_category?: Category;
  categories: Category[];
  capabilities: AppCapability[];
  releases: Release[];
  verification_summary: VerificationSummary;
  created_at: string;
  updated_at: string;
}

export interface SearchResponse {
  query: string;
  normalized_query: string;
  detected_categories: string[];
  suggested_categories: Category[];
  applied_filters: Record<string, any>;
  total_results: number;
  results: AppListItem[];
}
