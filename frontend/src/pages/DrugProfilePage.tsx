import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Activity,
  ArrowLeft,
  Building2,
  CalendarDays,
  Dna,
  DollarSign,
  ExternalLink,
  FlaskConical,
  Globe,
  Pill,
  Tags,
} from 'lucide-react';
import api, {
  type ClinicalTrialsResponse,
  type DrugProfile,
  type PublicDrugBiology,
} from '../lib/api';

const EMPTY_BIOLOGY: PublicDrugBiology = {
  drug: { id: 0, name_display: '' },
  identifiers: [],
  chembl_records: [],
  profiles: [],
  targets: [],
  diseases: [],
};

const EMPTY_TRIALS: ClinicalTrialsResponse = {
  total: 0,
  limit: 25,
  offset: 0,
  trials: [],
};

function formatValue(value: number | null): string {
  if (value === null || value === undefined) return 'N/A';
  if (value >= 1000) return `$${(value / 1000).toFixed(1)}B`;
  return `$${value.toFixed(0)}M`;
}

function formatLabel(value: string | null | undefined): string {
  if (!value) return 'Not reported';
  return value
    .split('_')
    .join(' ')
    .toLowerCase()
    .replace(/\b\w/g, (character: string) => character.toUpperCase());
}

function formatDate(value: string | null): string {
  if (!value) return '—';
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export default function DrugProfilePage() {
  const { drugId } = useParams();
  const [profile, setProfile] = useState<DrugProfile | null>(null);
  const [biology, setBiology] = useState<PublicDrugBiology>(EMPTY_BIOLOGY);
  const [trials, setTrials] = useState<ClinicalTrialsResponse>(EMPTY_TRIALS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!drugId) return;
    let cancelled = false;

    async function loadProfile() {
      setLoading(true);
      setError(null);
      try {
        const [profileResponse, biologyResponse, trialResponse] = await Promise.all([
          api.get<DrugProfile>(`/drug/${drugId}/profile`),
          api.get<PublicDrugBiology>(`/drugs/${drugId}/public-biology`).catch(() => ({
            data: EMPTY_BIOLOGY,
          })),
          api.get<ClinicalTrialsResponse>('/clinical-trials', {
            params: { drug_id: drugId, limit: 25 },
          }).catch(() => ({ data: EMPTY_TRIALS })),
        ]);
        if (!cancelled) {
          setProfile(profileResponse.data);
          setBiology(biologyResponse.data);
          setTrials(trialResponse.data);
        }
      } catch {
        if (!cancelled) setError('Drug profile could not be loaded.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadProfile();
    return () => {
      cancelled = true;
    };
  }, [drugId]);

  const relatedCompanies = useMemo(() => {
    if (!profile) return [];
    const companies = new Map<string, { id: number | null; name: string; role: string }>();
    for (const deal of profile.deals) {
      if (deal.principal_company) {
        companies.set(`principal:${deal.principal_company_id ?? deal.principal_company}`, {
          id: deal.principal_company_id,
          name: deal.principal_company,
          role: 'Principal',
        });
      }
      if (deal.partner_company) {
        companies.set(`partner:${deal.partner_company_id ?? deal.partner_company}`, {
          id: deal.partner_company_id,
          name: deal.partner_company,
          role: 'Partner',
        });
      }
    }
    return Array.from(companies.values());
  }, [profile]);

  if (loading) {
    return <div className="p-6 animate-pulse"><div className="h-8 w-64 bg-slate-800 rounded" /></div>;
  }
  if (error || !profile) {
    return <div className="p-6 text-red-400">{error || 'Drug not found'}</div>;
  }

  const phase = profile.phase_highest_now || profile.phase_highest_start;
  const publicProfile = biology.profiles[0];

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <Link to="/search" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-300 mb-4">
        <ArrowLeft className="w-4 h-4" /> Back
      </Link>

      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-purple-600/20 flex items-center justify-center">
          <Pill className="w-6 h-6 text-purple-400" />
        </div>
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-slate-100">{profile.name}</h1>
          <div className="flex flex-wrap gap-2 mt-2">
            {phase && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400">
                {formatLabel(phase)}
              </span>
            )}
            {publicProfile?.drug_type && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400">
                {formatLabel(publicProfile.drug_type)}
              </span>
            )}
            {biology.chembl_records.map((record) => (
              <a
                key={record.chembl_id}
                href={record.source_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 hover:text-emerald-300"
              >
                {record.chembl_id}<ExternalLink className="w-3 h-3" />
              </a>
            ))}
          </div>
          {publicProfile?.description && (
            <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-400">{publicProfile.description}</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <Kpi label="Total Deals" value={String(profile.total_deals)} />
        <Kpi label="Total Deal Value" value={formatValue(profile.total_deal_value)} />
        <Kpi label="Related Companies" value={String(relatedCompanies.length)} />
        <Kpi label="Linked Trials" value={String(trials.total)} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <SectionTitle icon={<Building2 className="w-4 h-4" />} title="Related Companies" />
          {relatedCompanies.length ? (
            <div className="space-y-2">
              {relatedCompanies.map((company) => (
                <div key={`${company.role}:${company.id ?? company.name}`} className="flex items-center justify-between gap-3 text-sm">
                  {company.id ? (
                    <Link to={`/company/${company.id}`} className="text-slate-300 truncate hover:text-white">
                      {company.name}
                    </Link>
                  ) : <span className="text-slate-300 truncate">{company.name}</span>}
                  <span className="text-xs text-slate-500">{company.role}</span>
                </div>
              ))}
            </div>
          ) : <EmptyText>No related companies found</EmptyText>}
        </section>

        <section className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-5">
          <SectionTitle icon={<Globe className="w-4 h-4" />} title="Current Territory Rights" />
          {profile.rights_holders.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-slate-500 border-b border-slate-800">
                  <th className="pb-2">Territory</th><th className="pb-2">Rights Holder</th><th className="pb-2">Deal</th>
                </tr></thead>
                <tbody>{profile.rights_holders.map((right) => (
                  <tr key={`${right.territory}:${right.deal_id}`} className="border-t border-slate-800/50">
                    <td className="py-2 text-slate-300">{right.territory}</td>
                    <td className="py-2 text-slate-400">{right.rights_holder || '—'}</td>
                    <td className="py-2 text-slate-500 text-xs">{right.deal_title || (right.deal_id ? `#${right.deal_id}` : '—')}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : <EmptyText>No territory data available</EmptyText>}
        </section>
      </div>

      <section className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-6">
        <SectionTitle icon={<Dna className="w-4 h-4" />} title="Public Drug & Target Biology" />
        {biology.identifiers.length || biology.targets.length || biology.diseases.length ? (
          <div className="space-y-6">
            <div>
              <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">Source-verified identifiers</h3>
              <div className="flex flex-wrap gap-2">
                {biology.identifiers.map((identifier) => {
                  const label = `${formatLabel(identifier.identifier_type)}: ${identifier.identifier_value}`;
                  return identifier.source_reference ? (
                    <a key={`${identifier.identifier_type}:${identifier.identifier_value}`} href={identifier.source_reference} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded bg-slate-800 px-2 py-1 text-xs text-slate-300 hover:text-white">
                      {label}<ExternalLink className="w-3 h-3" />
                    </a>
                  ) : <span key={`${identifier.identifier_type}:${identifier.identifier_value}`} className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300">{label}</span>;
                })}
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <div>
                <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2 flex items-center gap-2"><Activity className="w-4 h-4" /> Targets & mechanisms</h3>
                {biology.targets.length ? (
                  <div className="space-y-2">
                    {biology.targets.slice(0, 12).map((target) => (
                      <div key={`${target.chembl_id}:${target.ensembl_id}:${target.mechanism_of_action}`} className="rounded-lg border border-slate-800 p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div><div className="font-medium text-slate-200">{target.approved_symbol}</div><div className="text-xs text-slate-500">{target.approved_name}</div></div>
                          <a href={`https://platform.opentargets.org/target/${target.ensembl_id}`} target="_blank" rel="noreferrer" className="text-xs text-cyan-400 hover:text-cyan-300">{target.ensembl_id}</a>
                        </div>
                        <div className="mt-2 text-xs text-slate-400">{target.mechanism_of_action || target.target_name || 'Mechanism not reported'}{target.action_type ? ` · ${formatLabel(target.action_type)}` : ''}</div>
                        {target.uniprot_records?.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-2">
                            {target.uniprot_records.map((record) => (
                              <a
                                key={record.requested_accession}
                                href={record.source_url}
                                target="_blank"
                                rel="noreferrer"
                                title={record.protein_name || record.uniprot_id || record.primary_accession}
                                className="inline-flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300"
                              >
                                UniProt {record.primary_accession}<ExternalLink className="w-3 h-3" />
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                    {biology.targets.length > 12 && <CountNote shown={12} total={biology.targets.length} />}
                  </div>
                ) : <EmptyText>No target mechanism is available for this exact public mapping.</EmptyText>}
              </div>

              <div>
                <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2 flex items-center gap-2"><FlaskConical className="w-4 h-4" /> Public indication stages</h3>
                {biology.diseases.length ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {biology.diseases.slice(0, 12).map((disease) => (
                      <div key={`${disease.chembl_id}:${disease.disease_id}`} className="rounded-lg border border-slate-800 p-3">
                        <div className="text-sm text-slate-200">{disease.name}</div>
                        <div className="mt-1 text-xs text-slate-500">{formatLabel(disease.maximum_clinical_stage)} · {disease.disease_id}</div>
                      </div>
                    ))}
                    {biology.diseases.length > 12 && <CountNote shown={12} total={biology.diseases.length} />}
                  </div>
                ) : <EmptyText>No public indication stages are available for this mapping.</EmptyText>}
              </div>
            </div>
          </div>
        ) : <EmptyText>Public-source enrichment has not reached this asset yet.</EmptyText>}
      </section>

      <section className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-6">
        <SectionTitle icon={<CalendarDays className="w-4 h-4" />} title={`Clinical Trials (${trials.total})`} />
        {trials.trials.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-slate-500 border-b border-slate-800">
                <th className="pb-2">Study</th><th className="pb-2">Phase</th><th className="pb-2">Status</th><th className="pb-2">Primary completion</th>
              </tr></thead>
              <tbody>{trials.trials.map((trial) => (
                <tr key={trial.nct_id} className="border-t border-slate-800/50 align-top">
                  <td className="py-3 pr-4 min-w-80"><a href={trial.source_url} target="_blank" rel="noreferrer" className="text-slate-200 hover:text-white">{trial.brief_title}</a><div className="mt-1 text-xs text-slate-500">{trial.nct_id}{trial.lead_sponsor_name ? ` · ${trial.lead_sponsor_name}` : ''}</div></td>
                  <td className="py-3 pr-4 text-slate-400">{trial.phases.length ? trial.phases.map(formatLabel).join(', ') : '—'}</td>
                  <td className="py-3 pr-4 text-slate-400">{formatLabel(trial.overall_status)}</td>
                  <td className="py-3 text-slate-500">{formatDate(trial.primary_completion_date)}</td>
                </tr>
              ))}</tbody>
            </table>
            {trials.total > trials.trials.length && <CountNote shown={trials.trials.length} total={trials.total} />}
          </div>
        ) : <EmptyText>No exact ClinicalTrials.gov asset links are available.</EmptyText>}
      </section>

      {(profile.indications.length > 0 || profile.technologies.length > 0) && (
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-6">
          <SectionTitle icon={<Tags className="w-4 h-4" />} title="Cortellis Indications & Technologies" />
          <div className="space-y-3">
            {profile.indications.length > 0 && <TagList label="Indications" values={profile.indications} />}
            {profile.technologies.length > 0 && <TagList label="Technologies" values={profile.technologies} />}
          </div>
        </section>
      )}

      <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <SectionTitle icon={<DollarSign className="w-4 h-4" />} title="Deal History" />
        {profile.deals.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-slate-500 border-b border-slate-800">
                <th className="pb-2">Title</th><th className="pb-2">Principal</th><th className="pb-2">Partner</th><th className="pb-2">Value</th><th className="pb-2">Date</th>
              </tr></thead>
              <tbody>{profile.deals.map((deal) => (
                <tr key={deal.id} className="border-t border-slate-800/50">
                  <td className="py-2 pr-4 text-slate-200">{deal.title || `Deal #${deal.id}`}</td>
                  <td className="py-2 pr-4 text-slate-400">{deal.principal_company || '—'}</td>
                  <td className="py-2 pr-4 text-slate-400">{deal.partner_company || '—'}</td>
                  <td className="py-2 pr-4 text-slate-300">{formatValue(deal.total_value)}</td>
                  <td className="py-2 text-slate-500 text-xs">{formatDate(deal.date_start)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <EmptyText>No deal history is available.</EmptyText>}
      </section>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return <div className="bg-slate-900 border border-slate-800 rounded-lg p-3"><div className="text-xs text-slate-500">{label}</div><div className="text-lg font-bold text-slate-200 mt-1">{value}</div></div>;
}

function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">{icon}{title}</h2>;
}

function EmptyText({ children }: { children: React.ReactNode }) {
  return <p className="text-slate-500 text-sm">{children}</p>;
}

function CountNote({ shown, total }: { shown: number; total: number }) {
  return <div className="text-xs text-slate-500 mt-2">Showing {shown} of {total}. Full records remain available through the API.</div>;
}

function TagList({ label, values }: { label: string; values: string[] }) {
  return <div><div className="text-xs text-slate-500 mb-2">{label}</div><div className="flex flex-wrap gap-2">{values.map((value) => <span key={value} className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300">{value}</span>)}</div></div>;
}
