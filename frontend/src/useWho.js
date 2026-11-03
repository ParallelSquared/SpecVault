import { useEffect, useState } from 'react';
import { WHO_CHANGED, whoAmI } from './api';

// The current name, kept in step with every other place it is shown: picking
// or forgetting it anywhere on the page, in another tab, or letting it lapse
// while the window sat in the background. In a file of its own because Vite's
// hot reload wants component files to export only components.
export function useWho() {
  const [name, setName] = useState(whoAmI);
  useEffect(() => {
    const refresh = () => setName(whoAmI());
    window.addEventListener(WHO_CHANGED, refresh);
    window.addEventListener('storage', refresh); // another tab
    window.addEventListener('focus', refresh);   // back after hours away
    return () => {
      window.removeEventListener(WHO_CHANGED, refresh);
      window.removeEventListener('storage', refresh);
      window.removeEventListener('focus', refresh);
    };
  }, []);
  return name;
}
