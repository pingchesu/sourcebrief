import { redirect } from 'next/navigation';

// Connect-source flow now lives inside the canonical /sources hub (PR2).
// Keep this route reachable so existing links/bookmarks do not 404.
export default function ImportRedirect() {
  redirect('/sources');
}
