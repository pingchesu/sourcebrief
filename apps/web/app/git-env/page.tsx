import { redirect } from 'next/navigation';

// Git environment settings moved into the Advanced section of each source in
// the canonical /sources hub (PR2). Keep this route reachable to avoid 404s.
export default function GitEnvRedirect() {
  redirect('/sources');
}
