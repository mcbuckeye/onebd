import { useNavigate, useParams } from 'react-router-dom';
import DealDetailPanel from '../components/DealDetailPanel';

export default function DealPage() {
  const { dealId } = useParams();
  const navigate = useNavigate();
  const parsedDealId = Number(dealId);

  if (!Number.isInteger(parsedDealId) || parsedDealId <= 0) {
    return <div className="p-6 text-red-400">Invalid deal identifier.</div>;
  }

  return (
    <DealDetailPanel
      dealId={parsedDealId}
      apiBase="/api"
      onClose={() => navigate(-1)}
      onEntityClick={(entity) => {
        if (entity.type === 'company') navigate(`/company/${entity.id}`);
        if (entity.type === 'drug') navigate(`/drug/${entity.id}`);
      }}
    />
  );
}
