import { Settings } from "lucide-react";
import { useEffect, useState } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { getInitials } from "@/lib/identity";
import { strings } from "@/lib/strings";

import "./ChatHeader.css";

interface ChatHeaderProps {
  adminMode?: boolean;
  avatarUrl?: string;
  name: string;
  onOpenSettings?: () => void;
}

export function ChatHeader({
  adminMode = false,
  avatarUrl,
  name,
  onOpenSettings,
}: ChatHeaderProps) {
  const initials = getInitials(name);
  const [showAvatarImage, setShowAvatarImage] = useState(Boolean(avatarUrl));

  useEffect(() => {
    setShowAvatarImage(Boolean(avatarUrl));
  }, [avatarUrl]);

  return (
    <header className="chat-header">
      <div className="chat-header__inner">
        <div className="chat-header__identity">
          <Avatar className="chat-header__avatar" size="lg">
            {avatarUrl && showAvatarImage ? (
              <img
                alt={name}
                className="aspect-square size-full object-cover"
                onError={() => {
                  setShowAvatarImage(false);
                }}
                src={avatarUrl}
              />
            ) : null}
            {!showAvatarImage ? (
              <AvatarFallback>{initials}</AvatarFallback>
            ) : null}
          </Avatar>
          <div>
            <p className="chat-header__status">{strings.headerStatus}</p>
            <h1 className="chat-header__name">{name}</h1>
          </div>
        </div>

        {adminMode ? (
          <div className="chat-header__actions">
            <Button
              aria-label={strings.profileSettings}
              onClick={onOpenSettings}
              size="icon-sm"
              type="button"
              variant="outline"
            >
              <Settings size={18} />
            </Button>
          </div>
        ) : null}
      </div>
    </header>
  );
}
