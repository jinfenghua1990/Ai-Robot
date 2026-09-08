import { parseStageDate } from '../data/ipoProjects';

export function computeIpoProgress(project, now) {
  const enriched = project.stages.map((stage) => ({ ...stage, ms: parseStageDate(stage.date) }));
  let currentIdx = -1;
  enriched.forEach((stage, index) => {
    if (stage.ms != null && stage.ms <= now) currentIdx = index;
  });
  const nextIdx = enriched.findIndex((stage) => stage.ms != null && stage.ms > now);
  return enriched.map((stage, index) => {
    let status;
    if (stage.ms == null) status = 'unknown';
    else if (index <= currentIdx) status = 'done';
    else if (index === nextIdx) status = 'active';
    else status = 'upcoming';
    return { ...stage, status };
  }).reduce((result, stage, index) => {
    result.stages.push(stage);
    if (stage.status === 'active') result.nextIdx = index;
    return result;
  }, { stages: [], nextIdx: -1, currentIdx });
}
