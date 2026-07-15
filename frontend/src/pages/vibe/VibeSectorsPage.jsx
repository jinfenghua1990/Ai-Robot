import { useParams } from 'react-router-dom';
import VibeEmbed from '../../components/VibeEmbed';

export default function VibeSectorsPage() {
  const { key } = useParams();
  return <VibeEmbed path={key ? `/sectors/${key}` : '/sectors'} title="Vibe 板块中心" />;
}
