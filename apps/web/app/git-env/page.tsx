import { redirect } from 'next/navigation';

// Git indexing settings now live in Settings alongside workspace/project scope.
// Keep this route reachable to avoid 404s from old bookmarks.
export default function GitEnvRedirect() {
  redirect('/config');
}
