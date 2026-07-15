import { useSearchParams } from 'react-router-dom';
import VibeEmbed from '../../components/VibeEmbed';

export default function VibeStockDataPage() {
  const [params] = useSearchParams();
  const code = params.get('code');
  const path = code ? `/stock-data?code=${code}` : '/stock-data';
  return <VibeEmbed path={path} title="Vibe 个股数据" />;
}
