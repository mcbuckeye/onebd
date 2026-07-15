import { useState } from 'react';
import { Newspaper, Clock } from 'lucide-react';
import { Link } from 'react-router-dom';
import api from '../lib/api';
import { useToast } from '../contexts/ToastContext';

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return '—';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function BriefingPage() {
  const toast = useToast();
  const [topic, setTopic] = useState('');
  const [briefing, setBriefing] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const generate = async (requestedTopic = topic) => {
    if (!requestedTopic.trim()) return;
    setLoading(true);
    setBriefing(null);
    try {
      const resp = await api.post('/briefings/generate', { topic: requestedTopic.trim() });
      setBriefing(resp.data);
    } catch (e) {
      console.error(e);
      toast.error('Failed to generate the briefing');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Intelligence Briefings</h1>
        <p className="text-sm text-slate-500 mt-1">On-demand market intelligence reports</p>
      </div>

      <div className="flex gap-2 mb-6 max-w-xl">
        <input
          type="text" value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && generate()}
          placeholder="Brief me on... (e.g., ADC deals, Pfizer, oncology)"
          className="flex-1 px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        <button onClick={() => generate()} disabled={loading}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm font-medium"
        >
          {loading ? 'Generating...' : 'Generate'}
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-6">
        {['Oncology', 'ADC deals', 'Pfizer', 'M&A activity', 'bispecific antibodies', 'immuno-oncology'].map(q => (
          <button key={q} onClick={() => { setTopic(q); generate(q); }}
            className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-400 hover:text-slate-200"
          >{q}</button>
        ))}
      </div>

      {briefing && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold text-slate-100 mb-1">{briefing.title}</h2>
          <div className="flex items-center gap-2 text-xs text-slate-500 mb-6">
            <Clock className="w-3 h-3" />
            <span>Last {briefing.period_days} days</span>
            <span>• Generated {new Date(briefing.generated_at).toLocaleString()}</span>
          </div>
          <p className="mb-6 text-xs leading-5 text-slate-500">{briefing.methodology}</p>

          {briefing.sections?.map((section: any, i: number) => (
            <div key={i} className="mb-6">
              <h3 className="text-sm font-semibold text-blue-400 uppercase tracking-wider mb-3">{section.title}</h3>

              {section.title === 'Market Summary' && section.content && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="text-xs text-slate-500">Matching Deals</div>
                    <div className="text-2xl font-bold text-slate-200">{section.content.matching_deals}</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="text-xs text-slate-500">Top Area</div>
                    <div className="text-lg font-bold text-slate-200">{section.content.top_therapy || '—'}</div>
                  </div>
                </div>
              )}

              {section.title === 'Notable Deals' && Array.isArray(section.content) && (
                <div className="space-y-2">
                  {section.content.map((d: any, j: number) => (
                    <div key={j} className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0">
                      <div>
                        <Link to={`/deals/${d.id}`} className="text-sm text-slate-200 hover:text-blue-400 hover:underline">{d.title || `Deal ${d.id}`}</Link>
                        <div className="text-xs text-slate-500">{d.principal} → {d.partner} • {d.type}</div>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <div className="text-sm text-slate-300 font-medium">{formatValue(d.value)}</div>
                        <div className="text-xs text-slate-500">{d.date}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {section.title === 'Notable Deals' && Array.isArray(section.content) && section.content.length === 0 && (
                <p className="text-sm text-slate-400">No matching deals were found in this time window. This briefing does not imply that no historical records exist.</p>
              )}
            </div>
          ))}
        </div>
      )}

      {!briefing && !loading && (
        <div className="text-center py-16">
          <Newspaper className="w-16 h-16 text-slate-700 mx-auto mb-4" />
          <p className="text-slate-500">Enter a topic to generate an intelligence briefing</p>
        </div>
      )}
    </div>
  );
}
