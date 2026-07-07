/**
 * iOS PWA Install Hint
 * 
 * Affiche un petit toast non-bloquant UNE SEULE FOIS pour les utilisateurs iOS/Safari.
 * Explique comment installer l'app via "Partager > Ajouter à l'écran d'accueil".
 * 
 * Ce composant est 100% passif et optionnel.
 * Il ne force AUCUNE interaction et disparaît automatiquement après 8 secondes.
 * L'utilisateur peut le fermer ou le désactiver définitivement.
 */

import { useState, useEffect } from 'react';
import { X, Share } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';

const STORAGE_KEY = 'cardiocoach_ios_pwa_hint_dismissed';
const MIN_VISITS_BEFORE_SHOW = 2; // Afficher après 2 visites
const VISIT_COUNT_KEY = 'cardiocoach_visit_count';

export const IOSPWAHint = () => {
  const { t } = useLanguage();
  const [show, setShow] = useState(false);

  useEffect(() => {
    // Vérifier si on est sur iOS/Safari et pas déjà en mode standalone
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
    const isStandalone = window.navigator.standalone === true;
    const isSafari = /Safari/.test(navigator.userAgent) && !/Chrome/.test(navigator.userAgent);
    
    // Ne rien afficher si pas iOS/Safari ou déjà installé
    if (!isIOS || !isSafari || isStandalone) {
      return;
    }

    // Vérifier si déjà dismissé
    const dismissed = localStorage.getItem(STORAGE_KEY);
    if (dismissed === 'true') {
      return;
    }

    // Compter les visites
    const visitCount = parseInt(localStorage.getItem(VISIT_COUNT_KEY) || '0', 10) + 1;
    localStorage.setItem(VISIT_COUNT_KEY, String(visitCount));

    // Afficher seulement après X visites
    if (visitCount >= MIN_VISITS_BEFORE_SHOW) {
      // Délai avant affichage pour ne pas interrompre
      const timer = setTimeout(() => {
        setShow(true);
        
        // Auto-dismiss après 8 secondes
        const autoHide = setTimeout(() => {
          setShow(false);
          localStorage.setItem(STORAGE_KEY, 'true');
        }, 8000);
        
        return () => clearTimeout(autoHide);
      }, 3000);
      
      return () => clearTimeout(timer);
    }
  }, []);

  const dismiss = () => {
    setShow(false);
    localStorage.setItem(STORAGE_KEY, 'true');
  };

  if (!show) return null;

  return (
    <div 
      className="fixed bottom-20 left-4 right-4 z-50 animate-in slide-in-from-bottom-4 duration-300"
      role="alert"
      aria-live="polite"
    >
      <div className="bg-card/95 backdrop-blur-sm border border-border rounded-lg p-3 shadow-lg max-w-sm mx-auto">
        <div className="flex items-start gap-3">
          <div className="flex-shrink-0 w-8 h-8 bg-blue-500/20 rounded-full flex items-center justify-center">
            <Share className="w-4 h-4 text-blue-400" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-foreground mb-1">
              {t("pwa.installTitle")}
            </p>
            <p className="text-[10px] text-muted-foreground leading-relaxed">
              {t("pwa.installMessage")}
            </p>
          </div>
          <button
            onClick={dismiss}
            className="flex-shrink-0 p-1 hover:bg-muted rounded-full transition-colors"
            aria-label={t("pwa.close")}
          >
            <X className="w-4 h-4 text-muted-foreground" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default IOSPWAHint;
