import { redirect } from 'next/navigation';

// Repo-agent selection, briefs, drift audit, and the opt-in patch/PR workflow
// were consolidated into the canonical /workbench hub (PR3). Keep this route
// reachable so existing links/bookmarks do not 404.
export default function RepoAgentsRedirect() {
  redirect('/workbench');
}
